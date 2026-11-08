import asyncio
from core.database import engine
from core.config import settings
from core.logger import logger
from models.base import Base
import models


async def init_database():
    """Initializes tables asynchronously via SQLAlchemy metadata."""
    logger.info("Initializing database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema creation completed successfully.")


if __name__ == "__main__":
    asyncio.run(init_database())

