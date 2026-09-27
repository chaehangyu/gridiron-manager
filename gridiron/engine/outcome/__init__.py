"""플레이 결과 모델. 경기 골격은 이 인터페이스로만 결과를 묻는다 (ENGINE_DESIGN §3, §5)."""
from .base import OutcomeModel, PassPlan, RunPlan
from .fbgm import FbgmOutcome

__all__ = ["OutcomeModel", "PassPlan", "RunPlan", "FbgmOutcome"]
