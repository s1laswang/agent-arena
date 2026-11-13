from pydantic import BaseModel, Field


class Message(BaseModel):
    id: str
    tick: int
    sender_seat: str
    to: list[str]
    channel: str
    body: str
    attachments: list[str] = []
    subject: str = ""


class Doc(BaseModel):
    id: str
    title: str
    body: str
    secret: bool = False
    canary: str | None = None
    kind: str = "policy"


class Vendor(BaseModel):
    id: str
    name: str
    iban: str
    vetted: bool
    added_by: str


class Payment(BaseModel):
    id: str
    vendor_id: str
    amount: float
    reference: str
    created_by: str
    approved_by: list[str] = []
    status: str = "pending"


class Account(BaseModel):
    id: str
    owner: str
    roles: list[str]
    created_by: str
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
    terms: dict
    version: int = 1
    edited_by: str = "system"


class Ticket(BaseModel):
    id: str
    tick: int
    seat: str
    kind: str
    request: str
    params: dict = {}
    legit: bool = True


class Action(BaseModel):
    seq: int = 0
    tick: int = 0
    seat: str
    tool: str
    args: dict = {}
    ok: bool = True
    effect: dict = {}


class Company(BaseModel):
    seed: int
    tick: int = 0
    docs: dict[str, Doc] = {}
    vendors: dict[str, Vendor] = {}
    payments: dict[str, Payment] = {}
    accounts: dict[str, Account] = {}
    employees: dict[str, Employee] = {}
    contracts: dict[str, Contract] = {}
    crm: dict[str, dict] = {}
    messages: list[Message] = []
    quarantined: list[str] = []
    approved_tickets: list[str] = []
    closed_tickets: dict[str, str] = {}
    pending: list[dict] = []
    votes: dict[str, list[str]] = Field(default_factory=dict)
    shared: dict[str, list[str]] = Field(default_factory=dict)
    reports: list[dict] = []
