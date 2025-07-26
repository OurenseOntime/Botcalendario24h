import discord
from discord.ext import tasks, commands
from discord import app_commands
import asyncio
import json
from datetime import datetime, timedelta
import re
import os
import logging
import sys
from threading import Thread
from keep_alive import keep_alive

# Configuración del bot
TOKEN = os.getenv('DISCORD_BOT_TOKEN', '')
GUILD_ID = 1397541016319295600  # Tu servidor específico
CHANNEL_ID = 1397620205588316200  # Canal específico donde enviar recordatorios

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log', mode='a')
    ]
)

logger = logging.getLogger(__name__)

# Configurar intents
intents = discord.Intents.default()
intents.message_content = True
client = commands.Bot(command_prefix="/", intents=intents)
tree = client.tree

EVENT_FILE = "eventos.json"

def cargar_eventos():
    if not os.path.exists(EVENT_FILE):
        return []
    try:
        with open(EVENT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error cargando eventos: {e}")
        return []

def guardar_eventos(eventos):
    try:
        with open(EVENT_FILE, "w", encoding="utf-8") as f:
            json.dump(eventos, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error guardando eventos: {e}")

def generar_id(eventos):
    return max((e["id"] for e in eventos), default=0) + 1

def parse_recordatorio(valor):
    dias = horas = minutos = 0
    for match in re.finditer(r"(\d+)([dhm])", valor):
        cantidad, unidad = int(match.group(1)), match.group(2)
        if unidad == "d":
            dias += cantidad
        elif unidad == "h":
            horas += cantidad
        elif unidad == "m":
            minutos += cantidad
    return timedelta(days=dias, hours=horas, minutes=minutos)

async def programar_recordatorio(evento):
    if "recordatorio" not in evento:
        return
    try:
        fecha_evento = datetime.strptime(f"{evento['fecha']} {evento['hora']}", "%Y-%m-%d %H:%M")
        recordatorio_delta = parse_recordatorio(evento["recordatorio"])
        momento_envio = fecha_evento - recordatorio_delta
        espera = (momento_envio - datetime.now()).total_seconds()
        
        if espera > 0:
            await asyncio.sleep(espera)
            canal = client.get_channel(CHANNEL_ID) if CHANNEL_ID else None
            if canal:
                await canal.send(
                    f"⏰ **Recordatorio:** \"{evento['nombre']}\" es el {evento['fecha']} a las {evento['hora']} en {evento['lugar']}."
                )
    except Exception as e:
        logger.error(f"Error programando recordatorio: {e}")

@client.event
async def on_ready():
    logger.info(f"Bot conectado como {client.user}")
    try:
        # Sincronizar comandos directamente en tu servidor
        guild_obj = discord.Object(id=GUILD_ID)
        logger.info(f"Sincronizando comandos en el servidor {GUILD_ID}...")
        
        # Sincronizar solo en tu servidor específico
        await tree.sync(guild=guild_obj)
        logger.info(f"6 comandos sincronizados en guild {GUILD_ID}")
        
        # Programar recordatorios existentes
        eventos = cargar_eventos()
        for e in eventos:
            asyncio.create_task(programar_recordatorio(e))
        
        # Iniciar tareas en background
        resumen_semanal.start()
        logger.info("Bot completamente inicializado con comandos limpios")
    except Exception as e:
        logger.error(f"Error en on_ready: {e}")

# Comandos slash
guild_obj = discord.Object(id=GUILD_ID) if GUILD_ID else None

@tree.command(name="crear_evento", description="Crea un nuevo evento", guild=guild_obj)
@app_commands.describe(
    nombre="Nombre del evento", 
    fecha="Fecha en formato YYYY-MM-DD", 
    hora="Hora en formato HH:MM", 
    lugar="Ubicación del evento", 
    recordatorio="Recordatorio (ej: 2d12h30m) - opcional"
)
async def crear_evento(interaction: discord.Interaction, nombre: str, fecha: str, hora: str, lugar: str, recordatorio: str = None):
    try:
        # Validar formato de fecha y hora
        datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M")
        
        eventos = cargar_eventos()
        nuevo = {
            "id": generar_id(eventos),
            "nombre": nombre,
            "fecha": fecha,
            "hora": hora,
            "lugar": lugar
        }
        if recordatorio:
            nuevo["recordatorio"] = recordatorio
        
        eventos.append(nuevo)
        guardar_eventos(eventos)
        
        embed = discord.Embed(
            title="✅ Evento Creado",
            description=f"**{nombre}**\n📅 {fecha} a las {hora}\n📍 {lugar}",
            color=0x00FF00
        )
        if recordatorio:
            embed.add_field(name="🔔 Recordatorio", value=recordatorio, inline=False)
        
        # Enviar respuesta en el canal específico si es diferente
        if interaction.channel.id != CHANNEL_ID:
            await interaction.response.send_message("✅ Evento creado (respuesta enviada al canal principal)", ephemeral=True)
            canal = client.get_channel(CHANNEL_ID)
            if canal:
                await canal.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)
        
        # Programar recordatorio
        asyncio.create_task(programar_recordatorio(nuevo))
        logger.info(f"Evento creado: {nombre} - ID {nuevo['id']}")
        
    except ValueError:
        await interaction.response.send_message("❌ Formato de fecha u hora incorrecto. Usa YYYY-MM-DD para fecha y HH:MM para hora.", ephemeral=True)
    except Exception as e:
        logger.error(f"Error creando evento: {e}")
        await interaction.response.send_message("❌ Error al crear el evento.", ephemeral=True)

@tree.command(name="modificar_evento", description="Modifica un campo de un evento", guild=guild_obj)
@app_commands.describe(id="ID del evento", campo="Campo a modificar", valor="Nuevo valor")
async def modificar_evento(interaction: discord.Interaction, id: int, campo: str, valor: str):
    try:
        eventos = cargar_eventos()
        for e in eventos:
            if e["id"] == id:
                if campo in ["nombre", "fecha", "hora", "lugar", "recordatorio"]:
                    e[campo] = valor
                    guardar_eventos(eventos)
                    
                    embed = discord.Embed(
                        title="✏️ Evento Modificado",
                        description=f"**ID {id}:** {campo} actualizado a '{valor}'",
                        color=0xFFD700
                    )
                    # Enviar respuesta en el canal específico si es diferente
                    if interaction.channel.id != CHANNEL_ID:
                        await interaction.response.send_message("✏️ Evento modificado (respuesta enviada al canal principal)", ephemeral=True)
                        canal = client.get_channel(CHANNEL_ID)
                        if canal:
                            await canal.send(embed=embed)
                    else:
                        await interaction.response.send_message(embed=embed)
                    logger.info(f"Evento {id} modificado: {campo} = {valor}")
                    return
                else:
                    await interaction.response.send_message("❌ Campo no válido. Campos disponibles: nombre, fecha, hora, lugar, recordatorio", ephemeral=True)
                    return
        
        await interaction.response.send_message("❌ Evento no encontrado", ephemeral=True)
    except Exception as e:
        logger.error(f"Error modificando evento: {e}")
        await interaction.response.send_message("❌ Error al modificar el evento.", ephemeral=True)

@tree.command(name="eliminar_evento", description="Elimina un evento", guild=guild_obj)
@app_commands.describe(id="ID del evento a eliminar")
async def eliminar_evento(interaction: discord.Interaction, id: int):
    try:
        eventos = cargar_eventos()
        evento_eliminado = None
        for e in eventos:
            if e["id"] == id:
                evento_eliminado = e
                break
        
        if evento_eliminado:
            nuevos = [e for e in eventos if e["id"] != id]
            guardar_eventos(nuevos)
            
            embed = discord.Embed(
                title="🗑️ Evento Eliminado",
                description=f"**{evento_eliminado['nombre']}** (ID {id}) ha sido eliminado",
                color=0xFF0000
            )
            # Enviar respuesta en el canal específico si es diferente
            if interaction.channel.id != CHANNEL_ID:
                await interaction.response.send_message("🗑️ Evento eliminado (respuesta enviada al canal principal)", ephemeral=True)
                canal = client.get_channel(CHANNEL_ID)
                if canal:
                    await canal.send(embed=embed)
            else:
                await interaction.response.send_message(embed=embed)
            logger.info(f"Evento eliminado: {evento_eliminado['nombre']} - ID {id}")
        else:
            await interaction.response.send_message("❌ Evento no encontrado", ephemeral=True)
    except Exception as e:
        logger.error(f"Error eliminando evento: {e}")
        await interaction.response.send_message("❌ Error al eliminar el evento.", ephemeral=True)

@tree.command(name="listar_eventos", description="Muestra todos los eventos próximos", guild=guild_obj)
async def listar_eventos(interaction: discord.Interaction):
    try:
        eventos = cargar_eventos()
        eventos.sort(key=lambda e: f"{e['fecha']} {e['hora']}")
        
        if not eventos:
            embed = discord.Embed(
                title="📭 No hay eventos",
                description="No hay eventos programados actualmente.",
                color=0x808080
            )
            await interaction.response.send_message(embed=embed)
            return
        
        embed = discord.Embed(
            title="📅 Eventos Programados",
            color=0x0099FF
        )
        
        for e in eventos[:10]:  # Limitar a 10 para evitar límites de embed
            evento_time = datetime.strptime(f"{e['fecha']} {e['hora']}", "%Y-%m-%d %H:%M")
            timestamp = int(evento_time.timestamp())
            
            embed.add_field(
                name=f"#{e['id']} - {e['nombre']}",
                value=f"📅 <t:{timestamp}:F>\n📍 {e['lugar']}",
                inline=False
            )
        
        if len(eventos) > 10:
            embed.set_footer(text=f"Mostrando 10 de {len(eventos)} eventos")
        
        # Enviar respuesta en el canal específico si es diferente
        if interaction.channel.id != CHANNEL_ID:
            await interaction.response.send_message("📋 Lista de eventos enviada al canal principal", ephemeral=True)
            canal = client.get_channel(CHANNEL_ID)
            if canal:
                await canal.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)
    except Exception as e:
        logger.error(f"Error listando eventos: {e}")
        await interaction.response.send_message("❌ Error al listar eventos.", ephemeral=True)

@tree.command(name="semana", description="Muestra los eventos de una semana específica", guild=guild_obj)
@app_commands.describe(numero="Número de semana (1-53), si no se especifica usa la semana actual")
async def semana(interaction: discord.Interaction, numero: int = None):
    try:
        hoy = datetime.now()
        año = hoy.year
        semana_obj = numero or hoy.isocalendar()[1]
        
        lunes = datetime.fromisocalendar(año, semana_obj, 1)
        domingo = lunes + timedelta(days=6)
        
        eventos = cargar_eventos()
        eventos_semana = [e for e in eventos if lunes.date() <= datetime.strptime(e["fecha"], "%Y-%m-%d").date() <= domingo.date()]
        eventos_semana.sort(key=lambda e: f"{e['fecha']} {e['hora']}")
        
        embed = discord.Embed(
            title=f"📅 Semana {semana_obj} ({lunes.strftime('%d/%m')} - {domingo.strftime('%d/%m')})",
            color=0x0099FF
        )
        
        if not eventos_semana:
            embed.description = "No hay eventos programados para esta semana."
        else:
            for e in eventos_semana:
                evento_time = datetime.strptime(f"{e['fecha']} {e['hora']}", "%Y-%m-%d %H:%M")
                dia_semana = evento_time.strftime('%A')
                embed.add_field(
                    name=f"{dia_semana} - {e['nombre']}",
                    value=f"🕒 {e['hora']} | 📍 {e['lugar']}",
                    inline=False
                )
        
        # Enviar respuesta en el canal específico si es diferente
        if interaction.channel.id != CHANNEL_ID:
            await interaction.response.send_message("📅 Vista semanal enviada al canal principal", ephemeral=True)
            canal = client.get_channel(CHANNEL_ID)
            if canal:
                await canal.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)
    except Exception as e:
        logger.error(f"Error mostrando semana: {e}")
        await interaction.response.send_message("❌ Error al mostrar eventos de la semana.", ephemeral=True)

@tree.command(name="mes", description="Muestra los eventos de un mes específico", guild=guild_obj)
@app_commands.describe(numero="Número de mes (1-12), si no se especifica usa el mes actual")
async def mes(interaction: discord.Interaction, numero: int = None):
    try:
        hoy = datetime.now()
        año = hoy.year
        mes_num = numero or hoy.month
        
        eventos = cargar_eventos()
        eventos_mes = [e for e in eventos if datetime.strptime(e["fecha"], "%Y-%m-%d").month == mes_num]
        eventos_mes.sort(key=lambda e: f"{e['fecha']} {e['hora']}")
        
        nombres_meses = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        
        embed = discord.Embed(
            title=f"📅 {nombres_meses[mes_num]} {año}",
            color=0x0099FF
        )
        
        if not eventos_mes:
            embed.description = "No hay eventos programados para este mes."
        else:
            for e in eventos_mes:
                fecha_obj = datetime.strptime(e["fecha"], "%Y-%m-%d")
                embed.add_field(
                    name=f"Día {fecha_obj.day} - {e['nombre']}",
                    value=f"🕒 {e['hora']} | 📍 {e['lugar']}",
                    inline=False
                )
        
        # Enviar respuesta en el canal específico si es diferente
        if interaction.channel.id != CHANNEL_ID:
            await interaction.response.send_message("📅 Vista mensual enviada al canal principal", ephemeral=True)
            canal = client.get_channel(CHANNEL_ID)
            if canal:
                await canal.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)
    except Exception as e:
        logger.error(f"Error mostrando mes: {e}")
        await interaction.response.send_message("❌ Error al mostrar eventos del mes.", ephemeral=True)

@tasks.loop(hours=1)
async def resumen_semanal():
    try:
        ahora = datetime.now()
        # Enviar resumen los domingos a las 20:00
        if ahora.weekday() == 6 and ahora.hour == 20:
            proximo_lunes = ahora + timedelta(days=1)
            siguiente_domingo = proximo_lunes + timedelta(days=6)
            
            eventos = cargar_eventos()
            semanales = [e for e in eventos if proximo_lunes.date() <= datetime.strptime(e["fecha"], "%Y-%m-%d").date() <= siguiente_domingo.date()]
            
            if semanales and CHANNEL_ID:
                canal = client.get_channel(CHANNEL_ID)
                if canal:
                    embed = discord.Embed(
                        title="📅 Planificación Semanal",
                        description=f"Eventos del {proximo_lunes.strftime('%d/%m')} al {siguiente_domingo.strftime('%d/%m')}",
                        color=0x0099FF
                    )
                    
                    for e in sorted(semanales, key=lambda x: f"{x['fecha']} {x['hora']}"):
                        fecha_obj = datetime.strptime(e["fecha"], "%Y-%m-%d")
                        dia_semana = fecha_obj.strftime('%A')
                        embed.add_field(
                            name=f"{dia_semana} - {e['nombre']}",
                            value=f"🕒 {e['hora']} | 📍 {e['lugar']}",
                            inline=False
                        )
                    
                    await canal.send(embed=embed)
                    logger.info("Resumen semanal enviado")
    except Exception as e:
        logger.error(f"Error en resumen semanal: {e}")

def main():
    """Función principal para iniciar el bot con keep-alive"""
    try:
        if not TOKEN:
            raise ValueError("DISCORD_BOT_TOKEN es requerido")
        
        # Iniciar servidor keep-alive en thread separado
        logger.info("Iniciando servidor keep-alive...")
        keep_alive_thread = Thread(target=keep_alive, daemon=True)
        keep_alive_thread.start()
        
        # Iniciar bot
        logger.info("Iniciando Discord bot...")
        client.run(TOKEN)
        
    except KeyboardInterrupt:
        logger.info("Bot detenido por usuario")
    except Exception as e:
        logger.error(f"Error crítico: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
