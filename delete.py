# In a Python shell or script
from app.database import SessionLocal
from app.models.user import PendingUser

db = SessionLocal()
pending_user = db.query(PendingUser).filter(PendingUser.email == "skimmertest@gmail.com").first()
if pending_user:
    db.delete(pending_user)
    db.commit()
    print("Pending user deleted")
db.close()