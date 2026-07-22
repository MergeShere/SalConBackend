import multiprocessing
import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"

workers = 2 

worker_class = "uvicorn.workers.UvicornWorker"


timeout = 120
keepalive = 5