# Chatbot de avatares de la ECI (Unity + backend de voz)

Dos avatares (la Rectora y Oswaldo) que conversan por voz con el público del Encuentro de Padres de la
Escuela Colombiana de Ingeniería Julio Garavito. Unity 2022.3 + Ready Player Me en el cliente; un servidor
FastAPI en `backend/` hace voz → texto → respuesta → **voz clonada**, gratis y en local, en cualquier equipo
(la clonación local necesita un procesador Apple Silicon; en el resto se usa una voz genérica de respaldo).

**Para activar todo, sigue [`backend/README.md`](backend/README.md)** (instalación, claves, dónde poner el audio
de las voces, cómo arrancar, pruebas y medidas de eficiencia).

Resumen: `cd backend` → instalar → poner `GEMINI_API_KEY` en `.env` → `scripts.prepare_voice` con el audio de
cada personaje → `uvicorn app.main:app --port 5000` → en Unity, `VoiceAssistant` (W / Espacio para hablar,
Tab cambia de personaje, 0–9 preguntas pregrabadas, P inicia la intro).
