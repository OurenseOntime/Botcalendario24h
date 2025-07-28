import discord
import asyncio
import json
import re
import os
import logging
import sys
from threading import Thread
from keep_alive import keep_alive
from discord.ext import tasks, commands
from discord import app_commands
from datetime import datetime, timedelta
from supabase import create_client, Client
from zoneinfo import ZoneInfo


# Cargar variables de entorno
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TOKEN = os.getenv("TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
GUILD_ID = int(os.getenv("GUILD_ID"))




if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL y SUPABASE_KEY son requeridos")


supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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

    
def cargar_eventos():
    try:
        response = supabase.table("eventos").select("*").execute()
        return response.data if response.data else []
    except Exception as e:
        logger.error(f"Error cargando eventos desde Supabase: {e}")
        return []

def guardar_evento(evento):
    try:
        response = supabase.table("eventos").insert(evento).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error guardando evento en Supabase: {e}")
        return None
    
def actualizar_evento(id, campo, valor):
    try:
        data = {campo: valor}
        response = supabase.table("eventos").update(data).eq("id", id).execute()
        return response.data
    except Exception as e:
        logger.error(f"Error actualizando evento {id}: {e}")
        return None

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

def eliminar_evento(id):
    try:
        response = supabase.table("eventos").delete().eq("id", id).execute()
        return response.data
    except Exception as e:
        logger.error(f"Error eliminando evento {id}: {e}")
        return None

async def programar_recordatorio(evento):
    if "recordatorio" not in evento:
        return
    try:
        fecha_evento = datetime.strptime(f"{evento['fecha']} {evento['hora']}", "%Y-%m-%d %H:%M:%S")
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
    fecha="Fecha en formato DD-MM-YYYY",  # <-- Cambiar descripción
    hora="Hora en formato HH:MM", 
    lugar="Ubicación del evento", 
    recordatorio="Recordatorio (ej: 2d12h30m) - opcional"
)
async def crear_evento(interaction: discord.Interaction, nombre: str, fecha: str, hora: str, lugar: str, recordatorio: str = None):
    try:
        # Validar formato de fecha y hora (input DD-MM-YYYY)
        fecha_obj = datetime.strptime(fecha, "%d-%m-%Y")
        # Convertir a formato YYYY-MM-DD para la base de datos
        fecha_db = fecha_obj.strftime("%Y-%m-%d")
        # Validar hora
        datetime.strptime(hora, "%H:%M")
        
        nuevo = {
            "nombre": nombre,
            "fecha": fecha_db,
            "hora": hora,
            "lugar": lugar,
        }
        if recordatorio:
            nuevo["recordatorio"] = recordatorio

        evento_insertado = guardar_evento(nuevo)
        if not evento_insertado:
            await interaction.response.send_message("❌ Error al guardar en la base de datos.", ephemeral=True)
            return
        
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
        logger.info(f"Evento creado: {nombre}")
        
    except ValueError:
        await interaction.response.send_message("❌ Formato de fecha u hora incorrecto. Usa DD-MM-YYYY para fecha y HH:MM para hora.", ephemeral=True)
    except Exception as e:
        logger.error(f"Error creando evento: {e}")
        await interaction.response.send_message("❌ Error al crear el evento.", ephemeral=True)
 
@tree.command(name="modificar_evento", description="Modifica un campo de un evento", guild=guild_obj)
@app_commands.describe(id="ID del evento", campo="Campo a modificar", valor="Nuevo valor")
async def modificar_evento(interaction: discord.Interaction, id: int, campo: str, valor: str):
    try:
        campos_validos = ["nombre", "fecha", "hora", "lugar", "recordatorio"]

        if campo not in campos_validos:
            await interaction.response.send_message(
                f"❌ Campo no válido. Campos disponibles: {', '.join(campos_validos)}",
                ephemeral=True
            )
            return

        # Validaciones básicas de formato
        if campo == "fecha":
            try:
                datetime.strptime(valor, "%Y-%m-%d")
            except ValueError:
                await interaction.response.send_message("❌ Fecha inválida. Usa el formato YYYY-MM-DD", ephemeral=True)
                return

        if campo == "hora":
            try:
                datetime.strptime(valor, "%H:%M")
            except ValueError:
                await interaction.response.send_message("❌ Hora inválida. Usa el formato HH:MM", ephemeral=True)
                return

        # Verificar que el evento exista
        evento_res = supabase.table("eventos").select("*").eq("id", id).execute()
        if not evento_res.data:
            await interaction.response.send_message("❌ Evento no encontrado", ephemeral=True)
            return

        # Realizar la actualización
        response = supabase.table("eventos").update({campo: valor}).eq("id", id).execute()

        if response.status_code != 200:
            await interaction.response.send_message("❌ Error al actualizar en la base de datos", ephemeral=True)
            return

        # Construir respuesta
        embed = discord.Embed(
            title="✏️ Evento Modificado",
            description=f"**ID {id}:** {campo} actualizado a '{valor}'",
            color=0xFFD700
        )

        if interaction.channel.id != CHANNEL_ID:
            await interaction.response.send_message("✏️ Evento modificado (respuesta enviada al canal principal)", ephemeral=True)
            canal = client.get_channel(CHANNEL_ID)
            if canal:
                await canal.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

        logger.info(f"Evento {id} modificado: {campo} = {valor}")

    except Exception as e:
        logger.error(f"Error modificando evento: {e}")
        await interaction.response.send_message("❌ Error al modificar el evento.", ephemeral=True)

        
@tree.command(name="eliminar_evento", description="Elimina un evento", guild=guild_obj)
@app_commands.describe(id="ID del evento a eliminar")
async def eliminar_evento(interaction: discord.Interaction, id: int):
    try:
        await interaction.response.defer(ephemeral=True)  # ✅ Reservamos la interacción

        # Verificar si el evento existe antes de eliminar
        response = supabase.table("eventos").select("*").eq("id", id).execute()
        if not response.data:
            await interaction.followup.send("❌ Evento no encontrado")
            return

        evento_eliminado = response.data[0]

        # Ejecutar la eliminación
        delete_response = supabase.table("eventos").delete().eq("id", id).execute()

        if delete_response.data == []:
            await interaction.followup.send("❌ Error al eliminar el evento de la base de datos.")
            return

        embed = discord.Embed(
            title="🗑️ Evento Eliminado",
            description=f"**{evento_eliminado['nombre']}** (ID {id}) ha sido eliminado",
            color=0xFF0000
        )

        if interaction.channel.id != CHANNEL_ID:
            await interaction.followup.send("🗑️ Evento eliminado (respuesta enviada al canal principal)")
            canal = client.get_channel(CHANNEL_ID)
            if canal:
                await canal.send(embed=embed)
        else:
            await interaction.followup.send(embed=embed)

        logger.info(f"Evento eliminado: {evento_eliminado['nombre']} - ID {id}")

    except Exception as e:
        logger.error(f"Error eliminando evento: {e}")
        try:
            await interaction.followup.send("❌ Error al eliminar el evento.")
        except:
            pass  # Silenciar si ya fue respondido


        
@tree.command(name="listar_eventos", description="Muestra todos los eventos próximos", guild=guild_obj)
async def listar_eventos(interaction: discord.Interaction):
    try:
        # Obtener eventos ordenados por fecha y hora
        response = supabase.table("eventos").select("*").order("fecha", desc=False).order("hora", desc=False).execute()
        eventos = response.data if response.data else []

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

        for e in eventos[:10]:  # Limitar a 10 para evitar límite de caracteres
            try:
                evento_time = datetime.strptime(f"{e['fecha']} {e['hora']}", "%Y-%m-%d %H:%M:%S")
            except ValueError:
                evento_time = datetime.strptime(f"{e['fecha']} {e['hora']}", "%Y-%m-%d %H:%M")
            # Si tus horas están en UTC en la base de datos, usa la siguiente línea:
            # evento_time = evento_time.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Madrid"))
            # Si ya están en hora de Madrid, solo:
            evento_time = evento_time.replace(tzinfo=ZoneInfo("Europe/Madrid"))
            timestamp = int(evento_time.timestamp())

            embed.add_field(
                name=f"#{e['id']} - {e['nombre']}",
                value=f"📅 <t:{timestamp}:F>\n📍 {e['lugar']}",
                inline=False
            )

        if len(eventos) > 10:
            embed.set_footer(text=f"Mostrando 10 de {len(eventos)} eventos")

        # Enviar respuesta en canal correcto
        if interaction.channel.id != CHANNEL_ID:
            await interaction.response.send_message("📋 Lista de eventos enviada al canal principal", ephemeral=True)
            canal = client.get_channel(CHANNEL_ID)
            if canal:
                await canal.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

        logger.info("Lista de eventos enviada")

    except Exception as e:
        logger.error(f"Error listando eventos: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Error al listar eventos.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Error al listar eventos.", ephemeral=True)
        except Exception:
            pass
        
        
@tree.command(name="semana", description="Muestra los eventos de una semana específica", guild=guild_obj)
@app_commands.describe(numero="Número de semana (1-53), si no se especifica usa la semana actual")
async def semana(interaction: discord.Interaction, numero: int = None):
    try:
        hoy = datetime.now()
        año = hoy.year
        semana_obj = numero or hoy.isocalendar()[1]

        lunes = datetime.fromisocalendar(año, semana_obj, 1).date()
        domingo = lunes + timedelta(days=6)

        # Diccionario para traducir días de la semana al español
        dias_es = {
            "Monday": "Lunes",
            "Tuesday": "Martes",
            "Wednesday": "Miércoles",
            "Thursday": "Jueves",
            "Friday": "Viernes",
            "Saturday": "Sábado",
            "Sunday": "Domingo"
        }

        # Consulta a supabase con filtro entre lunes y domingo
        response = supabase.table("eventos").select("*") \
            .gte("fecha", lunes.isoformat()) \
            .lte("fecha", domingo.isoformat()) \
            .order("fecha", desc=False) \
            .order("hora", desc=False) \
            .execute()
            
        eventos_semana = response.data if response.data else []

        embed = discord.Embed(
            title=f"📅 Semana {semana_obj} ({lunes.strftime('%d/%m')} - {domingo.strftime('%d/%m')})",
            color=0x0099FF
        )

        if not eventos_semana:
            embed.description = "No hay eventos programados para esta semana."
        else:
            for e in eventos_semana:
                # Asegurarse de que el formato de hora sea compatible
                try:
                    evento_time = datetime.strptime(f"{e['fecha']} {e['hora']}", "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    evento_time = datetime.strptime(f"{e['fecha']} {e['hora']}", "%Y-%m-%d %H:%M")
                dia_semana_en = evento_time.strftime('%A')
                dia_semana = dias_es.get(dia_semana_en, dia_semana_en)
                embed.add_field(
                    name=f"{dia_semana} - {e['nombre']}",
                    value=f"🕒 {e['hora']} | 📍 {e['lugar']}",
                    inline=False
                )

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

        if mes_num < 1 or mes_num > 12:
            await interaction.response.send_message("❌ El número del mes debe estar entre 1 y 12.", ephemeral=True)
            return

        # Consulta a supabase
        response = supabase.table("eventos") \
            .select("*") \
            .gte("fecha", f"{año}-{mes_num:02d}-01") \
            .lt("fecha", f"{año}-{mes_num+1:02d}-01" if mes_num < 12 else f"{año+1}-01-01") \
            .order("fecha", desc=False) \
            .order("hora", desc=False) \
            .execute()

        eventos_mes = response.data if response.data else []
        if not eventos_mes:
            embed.description = "No hay eventos programados para este mes."
        else:
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


@tasks.loop(minutes=1)
async def resumen_semanal():
    try:
        ahora = datetime.now(ZoneInfo("Europe/Madrid"))
        # Diccionario para traducir días de la semana al español
        dias_es = {
            "Monday": "Lunes",
            "Tuesday": "Martes",
            "Wednesday": "Miércoles",
            "Thursday": "Jueves",
            "Friday": "Viernes",
            "Saturday": "Sábado",
            "Sunday": "Domingo"
        }
        # Enviar resumen los domingos a las 20:00 y para depuración hoy lunes a las 19:41
        enviar = False
        if ahora.weekday() == 6 and ahora.hour == 20:
            enviar = True

        if enviar:
            proximo_lunes = ahora + timedelta(days=(7 - ahora.weekday())) if ahora.weekday() != 0 else ahora
            proximo_lunes = proximo_lunes.replace(hour=0, minute=0, second=0, microsecond=0)
            siguiente_domingo = proximo_lunes + timedelta(days=6)

            # Filtrar eventos entre próximo lunes y siguiente domingo
            response = supabase.table("eventos") \
                .select("*") \
                .gte("fecha", proximo_lunes.strftime("%Y-%m-%d")) \
                .lte("fecha", siguiente_domingo.strftime("%Y-%m-%d")) \
                .order("fecha", desc=False) \
                .order("hora", desc=False) \
                .execute()
            
            embed = discord.Embed(
                title=f"📅 Planificación Semanal",
                description=f"Eventos del {proximo_lunes.strftime('%d/%m')} al {siguiente_domingo.strftime('%d/%m')}",
                color=0x0099FF
            )

            semanales = response.data if response.data else []
            
            if not semanales:
                embed.description = "No hay eventos programados para esta semana."

            if semanales and CHANNEL_ID:
                canal = client.get_channel(CHANNEL_ID)
                if canal:
                    for e in semanales:
                        fecha_obj = datetime.strptime(e["fecha"], "%Y-%m-%d")
                        dia_semana_en = fecha_obj.strftime('%A')
                        dia_semana = dias_es.get(dia_semana_en, dia_semana_en)
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
