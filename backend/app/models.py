from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class Brand(BaseModel):
    id: str
    name: str = ""
    created: float = 0.0
    source_root: str = ""


class Asset(BaseModel):
    id: str
    name: str
    kind: Literal["single", "grid-cell", "vector", "doc", "photo-scene", "ui-shot", "logo", "template", "charm", "bloom", "illustration"]
    tags: list[str] = []
    colors: list[str] = []
    usage: str = ""
    role_hints: list[str] = []
    semantic: str = ""
    png: str = ""
    source: str = ""
    bbox: Optional[list[float]] = None
    directly_usable: bool = True
    exact_required: bool = False
    brand_id: str = ""
    folder: str = ""
    quality: dict[str, Any] = {}
    use_cases: list[str] = []
    mismatches: list[str] = []
    rule_refs: list[str] = []


class LexiconEntry(BaseModel):
    id: str
    name: str
    family: str
    semantic: str = ""
    colors: list[str] = []
    asset_id: str = ""


class Technique(BaseModel):
    name: str
    applies_to: str = ""
    instruction: str


class ContextRule(BaseModel):
    name: str
    when: str
    then: str


class RecipeSlot(BaseModel):
    role: str
    description: str
    optional: bool = False


class Recipe(BaseModel):
    id: str
    name: str
    intent: str
    slots: list[RecipeSlot]
    example_refs: list[str] = []
    boldness: Literal["bold", "balanced", "simple"] = "balanced"


class Grammar(BaseModel):
    brand: str = ""
    palette: list[dict[str, str]] = []
    lexicon: list[LexiconEntry] = []
    techniques: list[Technique] = []
    context_rules: list[ContextRule] = []
    recipes: list[Recipe] = []
    logo_rules: dict[str, Any] = {}
    safe_zones: dict[str, Any] = {}
    typography: dict[str, str] = {}
    donts: list[str] = []


class CopyBlock(BaseModel):
    headline: str
    sub: str = ""
    body: list[str] = []
    cta: str = ""


class Zone(BaseModel):
    role: str
    rect: list[float] = Field(description="fractions x,y,w,h of canvas")
    text_free: bool = False
    content: str = ""
    style: dict[str, Any] = {}


class SlotFill(BaseModel):
    role: str
    asset_id: str
    why: str = ""
    placement: str = ""


class Brief(BaseModel):
    job_id: str
    use_case: str
    ratio: Literal["1:1", "4:5", "9:16", "16:9"] = "1:1"
    archetype: str = ""
    recipe_id: str = ""
    story: str = ""
    idea: str = ""
    color_story: str = ""
    copy: "CopyBlock"
    boldness: Literal["bold", "balanced", "simple"] = "balanced"
    slots: list[SlotFill] = []
    zones: list[Zone] = []
    violations: list[str] = []


class Cohort(BaseModel):
    id: str
    name: str
    angle: str = ""
    story: str = ""
    idea: str = ""
    color_story: str = ""
    recipe_id: str = ""
    boldness: Literal["bold", "balanced", "simple"] = "balanced"
    copy: "CopyBlock"
    slots: list[SlotFill] = []
    zones: list[Zone] = []


class CriticItem(BaseModel):
    check: str
    pass_: bool = Field(alias="pass", default=False)
    note: str = ""
    fix_prompt: str = ""

    model_config = {"populate_by_name": True}


class CriticReport(BaseModel):
    score: float = 0.0
    items: list[CriticItem] = []
    fixes: list[str] = []


class Layer(BaseModel):
    type: Literal["raster", "image", "text"]
    role: str
    src: str = ""
    asset_id: str = ""
    content: str = ""
    bbox: list[float] = Field(default_factory=lambda: [0, 0, 1, 1])
    style: dict[str, Any] = {}
    locked: bool = False


class Manifest(BaseModel):
    job_id: str
    variant_id: str
    canvas: dict[str, float] = {"w": 1024, "h": 1024}
    ratio: str = "1:1"
    layers: list[Layer] = []
    design_src: str = ""


class Variant(BaseModel):
    id: str
    prompt: str = ""
    image: str = ""
    brief: Optional[Brief] = None
    reports: list[CriticReport] = []
    best_report: Optional[CriticReport] = None
    status: Literal["pending", "composing", "judging", "fixing", "done", "failed"] = "pending"
    history: list[str] = []
    manifest: Optional[Manifest] = None


class TrailItem(BaseModel):
    id: str = ""
    stage: str
    label: str
    variant_id: str = ""
    image: str = ""
    score: float | None = None
    notes: list[str] = []
    ts: float = 0.0


class EditDraft(BaseModel):
    id: str
    parent: str = ""
    instruction: str = ""
    kind: str = ""
    image: str = ""
    manifest: str = ""
    status: Literal["pending", "running", "done", "failed"] = "pending"
    created: float = 0.0
    notes: list[str] = []


class Job(BaseModel):
    id: str
    brand_id: str = ""
    folder: str = ""
    use_case: str = ""
    ratio: str = "1:1"
    n_variants: int = 4
    status: Literal["pending", "briefing", "composing", "judging", "fixing", "selecting", "delivering", "editing", "done", "failed"] = "pending"
    variants: list[Variant] = []
    trail: list[TrailItem] = []
    edits: list[EditDraft] = []
    selected: str = ""
    error: str = ""
    log: list[str] = []
