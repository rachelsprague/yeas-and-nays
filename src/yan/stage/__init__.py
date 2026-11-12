"""Parse raw source files into flat Parquet tables for dbt.

Parsers keep values as recorded (strings, official wording). Type casting,
renaming, and business logic happen in dbt staging models.
"""
