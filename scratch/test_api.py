from src.auth import KISAuth
from src.api import KISAPI
from src.config_init import get_config
import os
from dotenv import load_dotenv

load_dotenv()
auth = KISAuth()
api = KISAPI(auth)
print("Import success")
