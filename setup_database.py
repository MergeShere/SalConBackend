# # setup_database.py
# import sys
# import os

# # Add the parent directory to the Python path
# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# from app.database import engine, Base

# def create_tables():
#     print("Creating all database tables...")
#     try:
#         # This will create all tables defined in models that inherit from Base
#         Base.metadata.create_all(bind=engine)
#         print("Success! All tables created.")
#         print("\nTables created:")
#         for table in Base.metadata.tables:
#             print(f"  - {table}")
#         return True
#     except Exception as e:
#         print(f" Error: {e}")
#         return False

# if __name__ == "__main__":
#     if create_tables():
#         print("\n Database setup complete! You can now register users.")
#         sys.exit(0)
#     else:
#         print("\n Database setup failed!")
#         sys.exit(1)