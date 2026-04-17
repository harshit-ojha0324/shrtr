// k6 load test: redirect hot path.
// Codes come from load/codes.json (written by `make seed`); selection is
// Zipf-skewed because real link traffic is skewed -- uniform selection would
// understate cache effectiveness.
//
// Run:  make load        (dockerized k6)
// or:   k6 run -e BASE_URL=http://localhost:8000 load/redirect_hot.js
//
// NOTE: redirects:0 -- we measure shrtr, not the redirect target.

import http from 'k6/http';
import { check } from 'k6';

const BASE = __ENV.BASE_URL || 'http://localhost:8000';
const codes = JSON.parse(open('./codes.json'));

export const options = {
  scenarios: {
    redirects: {
      executor: 'ramping-arrival-rate',
      startRate: 50,
      timeUnit: '1s',
      preAllocatedVUs: 100,
      maxVUs: 500,
      stages: [
        { target: Number(__ENV.TARGET_RPS || 500), duration: '1m' },
        { target: Number(__ENV.TARGET_RPS || 500), duration: '3m' },
        { target: 0, duration: '30s' },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.001'],
    // intentionally generous; tighten only after you have real local numbers
    http_req_duration: ['p(99)<250'],
  },
};

// crude Zipf-ish skew: rank r picked with P ~ 1/r over the first 1000 codes
function pickCode() {
  const n = Math.min(codes.length, 1000);
  const r = Math.floor(Math.exp(Math.random() * Math.log(n))); // rank in [1, n)
  return codes[Math.min(r, n) - 1];
}

export default function () {
  const res = http.get(`${BASE}/${pickCode()}`, { redirects: 0 });
  check(res, { 'status is 302': (r) => r.status === 302 });
}
