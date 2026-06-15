from datetime import datetime
from sqlalchemy import Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class Config(Base):
    __tablename__ = "configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(String, nullable=False)  # "acc" or "ajo"
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
