from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import os

# ── Database ──────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_db_url = os.environ.get("DATABASE_URL")

if _db_url:
    # Railway entrega "postgres://..." — SQLAlchemy 2.x requiere "postgresql://"
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    DATABASE_URL = _db_url
    engine = create_engine(DATABASE_URL)
else:
    DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'pedidos.db')}"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ── ORM Models ────────────────────────────────────────────────────────────────
class Pedido(Base):
    __tablename__ = "pedidos"

    id = Column(Integer, primary_key=True, index=True)
    restaurante = Column(String, nullable=False)
    trabajador = Column(String, nullable=False)
    nota = Column(Text, nullable=True)
    fecha = Column(String, nullable=False)
    hora = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.now)
    entregado = Column(Boolean, default=False)
    tiempo_entrega = Column(String, nullable=True)

    items = relationship("ItemPedido", back_populates="pedido", cascade="all, delete-orphan")


class ItemPedido(Base):
    __tablename__ = "items_pedido"

    id = Column(Integer, primary_key=True, index=True)
    pedido_id = Column(Integer, ForeignKey("pedidos.id"), nullable=False)
    nombre = Column(String, nullable=False)
    cantidad = Column(Float, nullable=False)
    unidad = Column(String, nullable=False)
    costo = Column(Float, nullable=True, default=0.0)

    pedido = relationship("Pedido", back_populates="items")


Base.metadata.create_all(bind=engine)


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Gestión de Pedidos — Tijuana")

static_dir = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ── Schemas ───────────────────────────────────────────────────────────────────
class ItemIn(BaseModel):
    nombre: str
    cantidad: float
    unidad: str
    costo: Optional[float] = 0.0


class PedidoIn(BaseModel):
    restaurante: str
    trabajador: str
    nota: Optional[str] = ""
    items: List[ItemIn]


class ItemOut(BaseModel):
    id: int
    nombre: str
    cantidad: float
    unidad: str
    costo: float

    class Config:
        from_attributes = True


class PedidoOut(BaseModel):
    id: int
    restaurante: str
    trabajador: str
    nota: Optional[str]
    fecha: str
    hora: str
    timestamp: datetime
    entregado: bool
    tiempo_entrega: Optional[str]
    items: List[ItemOut]

    class Config:
        from_attributes = True


# ── Dependency ────────────────────────────────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
def root():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.post("/pedidos", response_model=PedidoOut, status_code=201)
def crear_pedido(body: PedidoIn, db: Session = Depends(get_db)):
    if not body.items:
        raise HTTPException(status_code=422, detail="El pedido debe tener al menos un ítem.")

    now = datetime.now()
    pedido = Pedido(
        restaurante=body.restaurante,
        trabajador=body.trabajador,
        nota=body.nota,
        fecha=now.strftime("%Y-%m-%d"),
        hora=now.strftime("%H:%M"),
        timestamp=now,
    )
    db.add(pedido)
    db.flush()

    for it in body.items:
        db.add(ItemPedido(
            pedido_id=pedido.id,
            nombre=it.nombre,
            cantidad=it.cantidad,
            unidad=it.unidad,
            costo=it.costo or 0.0,
        ))

    db.commit()
    db.refresh(pedido)
    return pedido


@app.get("/pedidos", response_model=List[PedidoOut])
def listar_pedidos(db: Session = Depends(get_db)):
    return db.query(Pedido).order_by(Pedido.timestamp.desc()).all()


@app.patch("/pedidos/{pedido_id}/entregar")
def marcar_entregado(pedido_id: int, db: Session = Depends(get_db)):
    pedido = db.query(Pedido).filter(Pedido.id == pedido_id).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado.")
    if pedido.entregado:
        raise HTTPException(status_code=400, detail="El pedido ya fue marcado como entregado.")

    delta = datetime.now() - pedido.timestamp
    minutos = max(1, int(delta.total_seconds() / 60))

    pedido.entregado = True
    pedido.tiempo_entrega = f"{minutos} min"
    db.commit()
    return {"ok": True, "tiempo_entrega": pedido.tiempo_entrega}


@app.patch("/pedidos/{pedido_id}/costo")
def actualizar_costo(pedido_id: int, item_id: int, costo: float, db: Session = Depends(get_db)):
    item = (
        db.query(ItemPedido)
        .filter(ItemPedido.id == item_id, ItemPedido.pedido_id == pedido_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Ítem no encontrado.")

    item.costo = max(0.0, costo)
    db.commit()
    return {"ok": True, "item_id": item_id, "costo": item.costo}
