from fastapi import FastAPI, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session
from sqlalchemy.future import select
from pydantic import BaseModel
from models import User, Base
from db import get_db, engine
import bcrypt
import jwt
import os
import json
from dotenv import load_dotenv
from langchain_community.chat_models import ChatOpenAI
from langchain.schema import HumanMessage
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferMemory
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from offers_dict import offers_dict
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import User
from transformers import pipeline
from fastapi import Body

app = FastAPI()

# Load environment variables from .env file
load_dotenv()

# Ensure the SECRET_KEY is loaded
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("No SECRET_KEY set for JWT encoding")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(token, os.getenv("SECRET_KEY"), algorithms=["HS256"])
        user_id = payload.get("id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid JWT token")
        async with db as session:
            result = await session.execute(select(User).filter(User.id == user_id))
            user = result.scalars().first()
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            return user
    except:
        raise HTTPException(status_code=401, detail="Invalid JWT token")
    
# router = APIRouter()
# app.include_router(router)

# Pydantic models for request bodies
class UserRegister(BaseModel):
    email: str
    password: str
    name: str
    gender: str
    current_city: str
    age: int

class UserLogin(BaseModel):
    email: str
    password: str

class ChatRequest(BaseModel):
    message: str

# Create DB tables
@app.on_event("startup")
async def startup_event():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# Registration API
@app.post("/register/")
async def register_user(user: UserRegister, db: Session = Depends(get_db)):
    async with db as session:
        existing_user = await session.execute(select(User).filter(User.email == user.email))
        if existing_user.scalars().first():
            raise HTTPException(status_code=400, detail="Email already registered")
        
        hashed_password = bcrypt.hashpw(user.password.encode(), bcrypt.gensalt()).decode('utf-8')
        new_user = User(email=user.email, hashed_password=hashed_password, name=user.name, gender=user.gender, current_city=user.current_city, age=user.age)
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)
        return {"message": "User registered successfully", "user_id": new_user.id}

# Login API
@app.post("/login/")
async def login_user(user: UserLogin, db: Session = Depends(get_db)):
    async with db as session:
        result = await session.execute(select(User).filter(User.email == user.email))
        user_in_db = result.scalars().first()
        if user_in_db:
            stored_hashed_password = user_in_db.hashed_password.encode('utf-8')
            if bcrypt.checkpw(user.password.encode(), stored_hashed_password):
                token = jwt.encode({"id": user_in_db.id}, SECRET_KEY, algorithm="HS256")
                return {"message": "Login successful", "user_id": user_in_db.id, "access_token": token}
        else:
            raise HTTPException(status_code=400, detail="Incorrect email or password")

@app.post("/chat")
async def chat(request: ChatRequest, user_id: int = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user_identity = user_id  # User ID from JWT
    message = request.message

    if not message:
        return Response(content=json.dumps({'error': 'Message is required'}), status_code=400)

    async with db as session:
        result = await session.execute(select(User).filter_by(id=user_identity))
        user = result.scalars().first()
        if not user:
            return Response(content=json.dumps({'error': 'User not found'}), status_code=404)

        chat_history = json.loads(user.chat_history)
        vector_store = initialize_chatbot()

        if message.lower() in ['exit', 'quit']:
            labels, scores = classify_chat_history(chat_history)
            matched_offers = get_offers(labels, offers_dict)

            user.labels = json.dumps(labels)
            user.scores = json.dumps(scores)
            user.offers = json.dumps(matched_offers)
            await session.commit()

            return {'answer': 'Chat session ended by user.', 'Matched Offers': matched_offers}

        # Proceed with chat as usual
        chat_model = ChatOpenAI(temperature=0.0, model_name='gpt-4-turbo')
        model = ConversationalRetrievalChain.from_llm(
            llm=chat_model,
            retriever=vector_store.as_retriever(search_kwargs={"k": 5}),
            memory=ConversationBufferMemory(memory_key="chat_history", return_messages=True)
        )

        response = model.invoke({"question": message, "chat_history": chat_history})
        chat_history.append({"question": message, "answer": response['answer']})
        user.chat_history = json.dumps(chat_history)
        await session.commit()

        return {'answer': response['answer']}        

@app.put("/update_user")
async def update_user(update_data: dict = Body(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user.email = update_data.get('email', user.email)
    if 'password' in update_data:
        user.hashed_password = bcrypt.hashpw(update_data['password'].encode(), bcrypt.gensalt()).decode('utf-8')
    user.name = update_data.get('name', user.name)
    user.gender = update_data.get('gender', user.gender)
    user.current_city = update_data.get('current_city', user.current_city)
    user.age = update_data.get('age', user.age)
    
    db.add(user)
    await db.commit()
    return {"message": "User details updated successfully"}

@app.get("/get_chat_history")
async def get_chat_history(user: User = Depends(get_current_user)):
    chat_history = json.loads(user.chat_history)
    return {"user_id": user.id, "chat_history": chat_history}

@app.get("/get_offers")
async def get_offers_for_user(user: User = Depends(get_current_user)):
    offers = json.loads(user.offers)
    return {"user_id": user.id, "offers": offers}




def initialize_chatbot():
        embeddings = OpenAIEmbeddings(api_key=os.getenv('OPENAI_API_KEY'))
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=100, chunk_overlap=0)
        persist_directory = "E:/TransData/Internal-wanderly-app-dev/FireCrawl/TravelDataChromaStore"
        vector_store = Chroma(
            collection_name="travel_data",
            embedding_function=embeddings,
            persist_directory=persist_directory
        )
        return vector_store
    
def classify_chat_history(chat_history):

    candidate_labels = [
        "Direct Flights", "Connected Flights", "Discounted Flights", "Round Trips", "One Way Trips", "Rentals",  
        "1 Star Hotels", "2 Star Hotels", "3 Star Hotels", "4 Star Hotels", "5 Star Hotels",  
        "Restaurants  and Food", "Cultural Activities",
        "Outdoor Activities", "Shopping Malls" 
    ]

    classifier = pipeline("zero-shot-classification", model="facebook/bart-large-mnli",  multi_label=True)
    sequence = json.dumps(chat_history, indent=4)
    output = classifier(sequence, candidate_labels)

    # Sorting labels and scores by scores in descending order
    results = list(zip(output['labels'], output['scores']))
    results_sorted = sorted(results, key=lambda x: x[1], reverse=True)

    # Selecting top 3 results
    top_results = results_sorted[:3]
    print("TOP RESULTS", top_results)
    
    # Unzipping the top results
    top_labels, top_scores = zip(*top_results)
    return top_labels, top_scores

def get_offers(top_labels, offers_dict):
    matched_offers = []
    for label in top_labels:
        if label in offers_dict:
            print(f"Matched label: {label}")
            matched_offers.extend(offers_dict[label])
    return matched_offers

# Run the API with Uvicorn:
# uvicorn main:app --reload
