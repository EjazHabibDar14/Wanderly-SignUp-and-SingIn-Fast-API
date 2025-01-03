from sqlalchemy import Column, Integer, String, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.sql import func
import uuid
import json

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    name = Column(String)
    gender = Column(String)
    current_city = Column(String)
    age = Column(Integer)
    chat_history = Column(Text, default=json.dumps([]))
    labels = Column(JSON, nullable=True)
    scores = Column(JSON, nullable=True)
    offers = Column(JSON, nullable=True) 
