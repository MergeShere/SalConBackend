# add_oauth_columns.py
import os
from sqlalchemy import create_engine, text
from app.core.config import settings

# Get database URL
database_url = settings.DATABASE_URL
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(database_url)

# SQL commands to add the missing columns
sql_commands = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_oauth_user BOOLEAN DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(255)",
    "CREATE INDEX IF NOT EXISTS ix_users_google_id ON users (google_id)"
]

with engine.connect() as connection:
    for sql in sql_commands:
        try:
            connection.execute(text(sql))
            connection.commit()
            print(f"Successfully executed: {sql}")
        except Exception as e:
            print(f"Error executing {sql}: {e}")

print("OAuth columns added successfully!")