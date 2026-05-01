from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class Condition(str, Enum):
    NEW = "New"
    LIKE_NEW = "Like New"
    OPEN_BOX = "Open Box"
    REFURBISHED = "Refurbished"
    USED_GOOD = "Used - Good"
    USED_ACCEPTABLE = "Used - Acceptable"
    SALVAGE = "Salvage"
    FOR_PARTS = "For Parts"
    UNTESTED = "Untested Returns"
    UNKNOWN = "Unknown"


class Product(BaseModel):
    name: str
    normalized_name: Optional[str] = None
    condition: Condition = Condition.UNKNOWN
    quantity: int = 1
    listed_msrp: Optional[float] = None
    real_msrp: Optional[float] = None
    fake_msrp: bool = False
    model_number: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    weight_lbs: Optional[float] = None
    dimensions_inches: Optional[str] = None
