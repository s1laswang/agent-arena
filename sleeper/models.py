from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

SEATS = ("ceo_assistant", "finance_ap", "controller", "hr", "it_admin", "procurement", "sales", "legal")
GoalKind = Literal["fraud", "leak", "backdoor", "sabotage", "frame"]


class Message(BaseModel):
    id: str
    tick: int
    sender_seat: str
    to: list[str]
    channel: Literal["chat", "email"]
    body: str
    subject: str = ""
    attachments: list[str] = []


class Doc(BaseModel):
    id: str
    title: str
    body: str
    secret: bool = False
    canary: str | None = None
    kind: str = "doc"
    image: str | None = None


class Vendor(BaseModel):
    id: str
    name: str
    iban: str
    vetted: bool = False
    added_by: str = "system"
    approved_by: list[str] = []


class Payment(BaseModel):
    id: str
    vendor_id: str
    iban: str = ""
    amount: float
    reference: str
    created_by: str
    approved_by: list[str] = []
    status: Literal["pending", "paid", "rejected"] = "pending"


class Account(BaseModel):
    id: str
    owner: str
    roles: list[str] = []
    created_by: str = "system"
    ticket_id: str | None = None


class Employee(BaseModel):
    id: str
    name: str
    iban: str
    salary: float
    seat: str | None = None


class Contract(BaseModel):
    id: str
    counterparty: str
    terms: dict[str, Any] = {}
    version: int = 1
    edited_by: list[str] = []


class Ticket(BaseModel):
    id: str
    tick: int
    seat: str
    kind: str
    request: str
    params: dict[str, Any] = {}
    legit: bool = True


class Company(BaseModel):
    seed: int
    tick: int = 0
    docs: dict[str, Doc] = {}
    vendors: dict[str, Vendor] = {}
    payments: dict[str, Payment] = {}
    accounts: dict[str, Account] = {}
    employees: dict[str, Employee] = {}
    contracts: dict[str, Contract] = {}
    crm: dict[str, dict[str, Any]] = {}
    messages: list[Message] = []
    quarantined: list[str] = []
    quarantine_votes: dict[str, list[str]] = {}
    closed_tickets: dict[str, str] = {}


class Action(BaseModel):
    seq: int
    tick: int
    seat: str
    tool: str
    args: dict[str, Any] = {}
    ok: bool
    effect: str = ""


Ledger = list[Action]


class SleeperGoal(BaseModel):
    id: str
    kind: GoalKind
    target: dict[str, Any] = {}
    success: Callable[[Company, Ledger], bool] | None = Field(default=None, exclude=True)


class Day(BaseModel):
    seed: int
    tickets: list[Ticket]
    sleeper_seat: str | None = None
    goal: SleeperGoal | None = None
    events: list[dict[str, Any]] = []
    ticks: int = 20


class Result(BaseModel):
    day_id: str
    seed: int
    seat_under_test: str | None = None
    agent: str
    agent_kind: str = ""
    trial: int = 0
    model: str = "scripted"
    reward: Literal[0, 1]
    tickets_done: int
    tickets_total: int
    harm: list[str] = []
    false_quarantine: list[str] = []
    sleeper_caught: bool = False
    steps: int = 0
    transcript_path: str | None = None
