from sqlalchemy import BigInteger, Integer
from sqlalchemy.orm import DeclarativeBase

# BIGINT on PostgreSQL; plain INTEGER on SQLite so autoincrement works in tests.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    pass
