import os
import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv
from keep_alive import keep_alive
from datetime import datetime, timedelta
import asyncio

# 🔐 Cargar variables de entorno
load_dotenv()
TOKEN = os.getenv("TOKEN")
CANAL_ID = int(os.getenv("CANAL_ID", "0"))
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

# ⚙️ Configurar intents y bot
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ✅ Evento cuando el bot está listo
@client.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    canal = client.get_channel(CANAL_ID)
    if canal:
        await canal.send("🤖 Bot activo y sincronizado.")
    print(f"✅ Bot conectado como {client.user}")

# 🗂️ Variables iniciales para eventos
eventos = []
id_counter = 1

@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Bot conectado como {client.user}")
    planificacion_semanal.start()
    recordatorio_eventos.start()

@tree.command(name="crear_evento", description="Crea un evento con recordatorio opcional")
@app_commands.describe(nombre="Nombre del evento", fecha="Formato YYYY-MM-DD", hora="HH:MM (24h)", lugar="Lugar del evento", dias_recordatorio="Días antes para recordar")
async def crear_evento(interaction: discord.Interaction, nombre: str, fecha: str, hora: str, lugar: str, dias_recordatorio: int = 0):
    global id_counter
    evento = {
        "id": id_counter,
        "nombre": nombre,
        "fecha": fecha,
        "hora": hora,
        "lugar": lugar,
        "recordatorio": dias_recordatorio
    }
    eventos.append(evento)
    id_counter += 1
    await interaction.response.send_message(f"✅ Evento **{nombre}** creado para el {fecha} a las {hora} en {lugar}.")

@tree.command(name="eliminar_evento", description="Elimina un evento por ID")
async def eliminar_evento(interaction: discord.Interaction, id: int):
    global eventos
    eventos = [e for e in eventos if e["id"] != id]
    await interaction.response.send_message(f"🗑️ Evento con ID {id} eliminado.")

@tree.command(name="lista_eventos", description="Lista todos los eventos programados")
async def lista_eventos(interaction: discord.Interaction):
    if not eventos:
        await interaction.response.send_message("No hay eventos programados.")
        return
    mensaje = "**📅 Eventos programados:**\n"
    for e in eventos:
        mensaje += f"ID {e['id']} | {e['nombre']} – {e['fecha']} {e['hora']} @ {e['lugar']}\n"
    await interaction.response.send_message(mensaje)

@tree.command(name="semana", description="Muestra los eventos de la semana")
@app_commands.describe(numero="Número de semana (opcional)")
async def semana(interaction: discord.Interaction, numero: int = None):
    hoy = datetime.now()
    if numero:
        lunes = datetime.strptime(f"{hoy.year}-W{numero}-1", "%G-W%V-%u")
    else:
        lunes = hoy - timedelta(days=hoy.weekday())
    domingo = lunes + timedelta(days=6)
    semana_eventos = [e for e in eventos if lunes.date() <= datetime.strptime(e['fecha'], "%Y-%m-%d").date() <= domingo.date()]
    if not semana_eventos:
        await interaction.response.send_message("No hay eventos esta semana.")
        return
    mensaje = f"📅 **Eventos de la semana {lunes.isocalendar().week} ({lunes.date()} – {domingo.date()}):**\n"
    for e in semana_eventos:
        mensaje += f"✅ {e['fecha']} – {e['nombre']} a las {e['hora']} @ {e['lugar']}\n"
    await interaction.response.send_message(mensaje)

@tree.command(name="mes", description="Muestra los eventos del mes")
@app_commands.describe(numero="Número de mes (opcional)")
async def mes(interaction: discord.Interaction, numero: int = None):
    hoy = datetime.now()
    mes_actual = numero if numero else hoy.month
    eventos_mes = [e for e in eventos if datetime.strptime(e['fecha'], "%Y-%m-%d").month == mes_actual]
    if not eventos_mes:
        await interaction.response.send_message("No hay eventos este mes.")
        return
    mensaje = f"📅 **Eventos del mes {mes_actual}:**\n"
    for e in eventos_mes:
        mensaje += f"✅ {e['fecha']} – {e['nombre']} a las {e['hora']} @ {e['lugar']}\n"
    await interaction.response.send_message(mensaje)

@tasks.loop(minutes=60)
async def recordatorio_eventos():
    hoy = datetime.now()
    canal = client.get_channel(CANAL_ID)
    for evento in eventos:
        if evento["recordatorio"] <= 0:
            continue
        fecha_evento = datetime.strptime(f"{evento['fecha']} {evento['hora']}", "%Y-%m-%d %H:%M")
        recordatorio_fecha = fecha_evento - timedelta(days=evento["recordatorio"])
        if recordatorio_fecha.date() == hoy.date() and recordatorio_fecha.hour == hoy.hour:
            await canal.send(
                f"⏰ **Recordatorio:** {evento['nombre']} es el {evento['fecha']} a las {evento['hora']} en {evento['lugar']}"
            )

@tasks.loop(hours=24)
async def planificacion_semanal():
    ahora = datetime.now()
    if ahora.weekday() == 6 and ahora.hour == 20:  # Domingo a las 20:00
        canal = client.get_channel(CANAL_ID)
        lunes = ahora + timedelta(days=1)
        domingo = lunes + timedelta(days=6)
        semana_eventos = [e for e in eventos if lunes.date() <= datetime.strptime(e['fecha'], "%Y-%m-%d").date() <= domingo.date()]
        if semana_eventos:
            mensaje = "**📅 Planificación semanal:**\n"
            for e in semana_eventos:
                mensaje += f"✅ {e['fecha']} – {e['nombre']} a las {e['hora']} @ {e['lugar']}\n"
            await canal.send(mensaje)

keep_alive()
client.run(TOKEN)
