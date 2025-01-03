from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Use the asyncpg driver for PostgreSQL
DATABASE_URL = "postgresql+asyncpg://postgres:admin123@127.0.0.1:5432/wanderly(FastAPI)"
engine = create_async_engine(DATABASE_URL, echo=True)

AsyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=AsyncSession)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
