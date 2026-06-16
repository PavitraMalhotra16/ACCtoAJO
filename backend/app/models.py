from datetime import datetime
from sqlalchemy import Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class AccConfig(Base):
    __tablename__ = "acc_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    auth_type: Mapped[str] = mapped_column(String, nullable=False)  # "classic" | "technical"
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AjoConfig(Base):
    __tablename__ = "ajo_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
