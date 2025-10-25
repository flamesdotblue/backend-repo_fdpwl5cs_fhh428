from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime

class Game(BaseModel):
    """
    Chess games imported from external sources.
    Collection name: "game"
    """
    source: Literal["chesscom", "lichess"] = Field(..., description="Source of the game")
    username: str = Field(..., description="Primary player username associated with the import")
    white: Optional[str] = Field(None, description="White player username")
    black: Optional[str] = Field(None, description="Black player username")
    pgn: str = Field(..., description="Complete PGN for the game")
    rated: Optional[bool] = Field(None, description="Whether the game is rated")
    speed: Optional[str] = Field(None, description="bullet, blitz, rapid, classical, etc.")
    time_control: Optional[str] = Field(None, description="Time control string from the source")
    result: Optional[str] = Field(None, description="Game result from the perspective of the importing user or overall")
    end_time: Optional[datetime] = Field(None, description="Game end time if available")
    opening: Optional[str] = Field(None, description="Opening name if available")

class ImportRequest(BaseModel):
    username: str
    months: Optional[int] = Field(1, ge=1, le=12, description="How many months of archives to fetch (chess.com)")
    limit: Optional[int] = Field(50, ge=1, le=1000, description="Max games to import per username")
