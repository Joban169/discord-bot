import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Select, Modal, TextInput
import sqlite3
import asyncio
import datetime
import logging

# ---------------- CONFIG ---------------- #
PREFIX = "+"
BOT_INTENTS = discord.Intents.default()
BOT_INTENTS.message_content = True
BOT_INTENTS.members = True

FOUNDER_ROLE = 1435350376579600465
ADMIN_ROLE = 1435350682231111750
SUPPORT_ROLE = 1435350881292783666
EXCHANGER_ROLE = 1435351384722509926

CATEGORY_INR_TO_CRYPTO = 1435356449923403876
CATEGORY_CRYPTO_TO_INR = 1435356616026488974
CATEGORY_CRYPTO_TO_CRYPTO = 1435356713174958265
CLOSED_TICKETS_CATEGORY = None  # optional, can be added later

DB_PATH = "mixhaven.db"

# --------------- LOGGING ---------------- #
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --------------- DATABASE INIT ---------------- #
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            total_vouches INTEGER DEFAULT 0,
            total_amount_usd REAL DEFAULT 0,
            last_vouch_ts TEXT,
            role_tag TEXT DEFAULT ''
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rates (
            rate_type TEXT PRIMARY KEY,
            below_50 REAL,
            above_50 REAL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category TEXT,
            created_at TEXT,
            closed_at TEXT,
            form_data TEXT,
            status TEXT,
            claimed_by INTEGER
        )
    """)
    # Default rates
    cur.execute("INSERT OR IGNORE INTO rates (rate_type, below_50, above_50) VALUES ('i2c', 96, 92)")
    cur.execute("INSERT OR IGNORE INTO rates (rate_type, below_50, above_50) VALUES ('c2i', 92, 92.5)")
    con.commit()
    con.close()

# --------------- BOT CLASS ---------------- #
class MixHavenBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=PREFIX, intents=BOT_INTENTS)

    async def setup_hook(self):
        init_db()
        logging.info("Database initialized.")
        await self.tree.sync()

bot = MixHavenBot()

# --------------- UTILITIES ---------------- #
def electric_embed(title, desc=None, color=discord.Color.from_rgb(0, 102, 255)):
    embed = discord.Embed(title=title, description=desc or "", color=color)
    embed.set_footer(text="MixHaven Exchange System • Secure • Verified")
    return embed

async def add_user_stat(user_id: int, amount: float):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO users (user_id, total_vouches, total_amount_usd, last_vouch_ts) VALUES (?, ?, ?, ?)",
                    (user_id, 1, amount, str(datetime.datetime.utcnow())))
    else:
        cur.execute("UPDATE users SET total_vouches = total_vouches + 1, total_amount_usd = total_amount_usd + ?, last_vouch_ts = ? WHERE user_id=?",
                    (amount, str(datetime.datetime.utcnow()), user_id))
    con.commit()
    con.close()

# --------------- RATE COMMANDS ---------------- #
@bot.command(name="i2c")
async def i2c(ctx, amount: float):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT below_50, above_50 FROM rates WHERE rate_type='i2c'")
    below, above = cur.fetchone()
    rate = below if amount < 50 else above
    crypto = amount / rate
    embed = electric_embed("💱 INR → CRYPTO", f"**INR:** ₹{amount}\n**Rate:** {rate}/$\n**You Get:** ${crypto:.2f}")
    await ctx.send(embed=embed)
    con.close()

@bot.command(name="c2i")
async def c2i(ctx, amount: float):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT below_50, above_50 FROM rates WHERE rate_type='c2i'")
    below, above = cur.fetchone()
    rate = below if amount < 50 else above
    inr = amount * rate
    embed = electric_embed("💰 CRYPTO → INR", f"**USD:** ${amount}\n**Rate:** {rate}/$\n**You Get:** ₹{inr:.2f}")
    await ctx.send(embed=embed)
    con.close()

@bot.command(name="setrate")
@commands.has_any_role(ADMIN_ROLE, FOUNDER_ROLE)
async def setrate(ctx, rate_type: str, below: float, above: float):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("UPDATE rates SET below_50=?, above_50=? WHERE rate_type=?", (below, above, rate_type))
    con.commit()
    con.close()
    await ctx.send(embed=electric_embed("✅ Rates Updated", f"**{rate_type.upper()}** → Below $50: `{below}` | Above $50: `{above}`"))

# --------------- VOUCH SYSTEM ---------------- #
@bot.command(name="v")
async def vouch(ctx, user: discord.Member, amount: float, *, type_: str):
    embed = discord.Embed(
        description=f"🐾 +rep {user.mention}\n**EXCHANGED {type_.upper()} [{amount}$]**",
        color=discord.Color.gold()
    )
    embed.set_footer(text=f"mixhaven_vouch|{user.id}|{amount}")
    await ctx.send(embed=embed)
    await ctx.message.add_reaction("✅")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.embeds:
        embed = message.embeds[0]
        if embed.footer and embed.footer.text.startswith("mixhaven_vouch"):
            parts = embed.footer.text.split("|")
            if len(parts) == 3:
                exchanger_id = int(parts[1])
                amount = float(parts[2])
                exchanger = message.guild.get_member(exchanger_id)
                client = message.author
                await add_user_stat(exchanger.id, amount)
                await add_user_stat(client.id, amount)
                e = electric_embed("✅ Vouch Recorded",
                                   f"**Exchanger:** {exchanger.mention}\n**Client:** {client.mention}\n**Amount:** ${amount}\nBoth stats updated.")
                await message.channel.send(embed=e)
    await bot.process_commands(message)

@bot.command(name="stats")
async def stats(ctx, user: discord.Member = None):
    user = user or ctx.author
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT total_vouches, total_amount_usd FROM users WHERE user_id=?", (user.id,))
    row = cur.fetchone()
    if not row:
        await ctx.send(embed=electric_embed("📊 Stats", f"No vouches found for {user.mention}."))
    else:
        total, amt = row
        embed = electric_embed("📊 Vouch Stats", f"**User:** {user.mention}\n**Total Vouches:** {total}\n**Total Amount:** ${amt:.2f}")
        await ctx.send(embed=embed)
    con.close()

# --------------- TICKET SYSTEM ---------------- #
class TicketModal(Modal, title="MixHaven Exchange Form"):
    def __init__(self, category_name):
        super().__init__()
        self.category_name = category_name
        self.name = TextInput(label="Name / Tag", required=True)
        self.amount = TextInput(label="Amount", required=True)
        self.type = TextInput(label="Type (USDT, BTC, etc.)", required=True)
        self.method = TextInput(label="Payment Method (UPI/Wallet)", required=True)
        for comp in [self.name, self.amount, self.type, self.method]:
            self.add_item(comp)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        category_id = {
            "INR → CRYPTO": CATEGORY_INR_TO_CRYPTO,
            "CRYPTO → INR": CATEGORY_CRYPTO_TO_INR,
            "CRYPTO → CRYPTO": CATEGORY_CRYPTO_TO_CRYPTO
        }.get(self.category_name)
        category = guild.get_channel(category_id)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        channel = await guild.create_text_channel(f"ticket-{interaction.user.name}", category=category, overwrites=overwrites)
        embed = electric_embed("🎫 Welcome to MixHaven Support!",
                               f"Please describe your issue below.\n\n**Name:** {self.name.value}\n**Amount:** {self.amount.value}\n**Type:** {self.type.value}\n**Method:** {self.method.value}")
        await channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Ticket created: {channel.mention}", ephemeral=True)

class TicketSelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="💵 INR → CRYPTO", description="Exchange INR to Crypto"),
            discord.SelectOption(label="💰 CRYPTO → INR", description="Exchange Crypto to INR"),
            discord.SelectOption(label="🔁 CRYPTO → CRYPTO", description="Exchange between cryptos"),
        ]
        super().__init__(placeholder="Select Exchange Type...", options=options)

    async def callback(self, interaction: discord.Interaction):
        modal = TicketModal(self.values[0].split(" ", 1)[1].strip())
        await interaction.response.send_modal(modal)

class TicketPanel(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())

@bot.command(name="panel")
@commands.has_any_role(ADMIN_ROLE, FOUNDER_ROLE)
async def panel(ctx):
    embed = electric_embed("🎟️ MixHaven Ticket Panel", "Select an exchange type below to open a ticket.")
    await ctx.send(embed=embed, view=TicketPanel())

# --------------- TICKET MANAGEMENT COMMANDS ---------------- #
@bot.command(name="c")
@commands.has_any_role(EXCHANGER_ROLE, FOUNDER_ROLE)
async def claim(ctx):
    if "claimed-by" in ctx.channel.name:
        await ctx.send("Already claimed.")
        return
    await ctx.channel.edit(name=f"claimed-by-{ctx.author.name}")
    await ctx.send(embed=electric_embed("🎟️ Ticket Claimed", f"{ctx.author.mention} has claimed this ticket."))

@bot.command(name="uc")
@commands.has_any_role(EXCHANGER_ROLE, FOUNDER_ROLE)
async def unclaim(ctx):
    if "claimed-by" not in ctx.channel.name:
        await ctx.send("Ticket is not claimed.")
        return
    await ctx.channel.edit(name=f"ticket-{ctx.author.name}")
    await ctx.send(embed=electric_embed("🎟️ Unclaimed", f"{ctx.author.mention} has unclaimed this ticket."))

@bot.command(name="sent")
@commands.has_any_role(EXCHANGER_ROLE, FOUNDER_ROLE)
async def sent(ctx):
    await ctx.send(embed=electric_embed("✅ Transaction Sent", "Your transaction has been marked as **sent**."))
    await ctx.channel.edit(name=f"closed-ticket-{ctx.author.name}")

@bot.command(name="dn")
@commands.has_any_role(EXCHANGER_ROLE, FOUNDER_ROLE)
async def dn(ctx):
    await ctx.send(embed=electric_embed("⚠️ Deal Not Done", "This deal has been marked as **not completed**."))

@bot.command(name="ss")
@commands.has_any_role(EXCHANGER_ROLE, FOUNDER_ROLE)
async def ss(ctx):
    await ctx.send(embed=electric_embed("📸 Screenshot Sent", "Proof of payment or transfer screenshot shared."))

@bot.command(name="close")
@commands.has_any_role(SUPPORT_ROLE, ADMIN_ROLE, FOUNDER_ROLE)
async def close(ctx):
    await ctx.send(embed=electric_embed("🔒 Ticket Closed", "Ticket will now be archived."))
    await ctx.channel.edit(name=f"closed-{ctx.author.name}")
    await ctx.channel.set_permissions(ctx.channel.guild.default_role, send_messages=False)

# --------------- BASIC COMMANDS ---------------- #
@bot.command(name="help")
async def help_cmd(ctx):
    embed = electric_embed("📘 MixHaven Bot Commands", f"""
**Exchange**
`+i2c <amount>` – INR → CRYPTO  
`+c2i <amount>` – CRYPTO → INR  
`+setrate i2c/c2i <below> <above>` – Admin only

**Vouches**
`+v @user <amount> <type>` – Create vouch  
`+stats [@user]` – View vouch stats

**Tickets**
`+panel` – Create ticket panel  
`+c`, `+uc`, `+sent`, `+dn`, `+ss`, `+close` – Manage tickets
""")
    await ctx.send(embed=embed)

@bot.command(name="ping")
async def ping(ctx):
    await ctx.send(embed=electric_embed("🏓 Pong!", f"Latency: {round(bot.latency * 1000)} ms"))

@bot.command(name="about")
async def about(ctx):
    await ctx.send(embed=electric_embed("ℹ️ About MixHaven", "A secure and trusted exchange community powered by MixHaven Bot."))

# --------------- RUN ---------------- #
if __name__ == "__main__":
    TOKEN = "MTQzNTM2NDI0MjA3MjE0NjAxMA.GsaEVQ.7EJzX3YY0mXWJYBZ7zhSUgJO_6lQQux3eITh2Y"  # <---- Fill your Discord Bot token here
    bot.run(TOKEN)