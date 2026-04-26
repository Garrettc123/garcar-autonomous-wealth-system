"""
Garcar Constitutional Runtime
5-Phase AI Governance and Safety System
"""
from .constitution_kernel import ConstitutionKernel, ConstitutionMiddleware, CritiqueResult, Verdict, mount_constitution
from .action_gateway import ActionGateway, ExternalSystem, PolicyReceipt
from .capability_sharding import CapabilityShardManager, ShardID, ShardContext
from .safety_visor import SafetyVisor, EscalationLevel, VisorEvent, start_visor_background
from .self_improvement_arena import SelfImprovementArena, ArenaOutcome, ADVERSARIAL_SUITE

__all__ = [
    # Phase 1
    "ConstitutionKernel",
    "ConstitutionMiddleware",
    "CritiqueResult",
    "Verdict",
    "mount_constitution",
    # Phase 2
    "ActionGateway",
    "ExternalSystem",
    "PolicyReceipt",
    # Phase 3
    "CapabilityShardManager",
    "ShardID",
    "ShardContext",
    # Phase 4
    "SafetyVisor",
    "EscalationLevel",
    "VisorEvent",
    "start_visor_background",
    # Phase 5
    "SelfImprovementArena",
    "ArenaOutcome",
    "ADVERSARIAL_SUITE",
]
