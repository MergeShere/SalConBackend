# test_rds.py
import psycopg2
from psycopg2 import sql

try:
    # Connect to the default 'postgres' database first
    conn = psycopg2.connect(
        host="database-1.c2jmcmiyc1pk.us-east-1.rds.amazonaws.com",
        port=5432,
        user="postgres",
        password="S0570263", # Your password
        database="postgres"
    )
    
    # CRITICAL FIX: Enable autocommit for creating databases
    conn.autocommit = True
    
    print("✅ Connected to AWS RDS successfully!")
    
    cursor = conn.cursor()
    
    # Check if database exists
    cursor.execute("SELECT 1 FROM pg_database WHERE datname='salon_connect'")
    if not cursor.fetchone():
        print("Creating 'salon_connect' database...")
        cursor.execute(sql.SQL("CREATE DATABASE salon_connect"))
        print("✅ Created 'salon_connect' database successfully")
    else:
        print("ℹ️ 'salon_connect' database already exists")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")