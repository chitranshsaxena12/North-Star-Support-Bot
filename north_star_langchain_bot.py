import os
import re
from typing import Annotated
from typing_extensions import TypedDict
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import StateGraph, START
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.message import add_messages

# ─────────────────────────────────────────────────────────────────
#  State definition for LangGraph
# ─────────────────────────────────────────────────────────────────
class BotState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# ─────────────────────────────────────────────────────────────────
#  Mock Business Data
# ─────────────────────────────────────────────────────────────────
ORDER_DB = {
    "111": "Shipped — arriving tomorrow 🚚",
    "222": "Processing — ships within 24 hours 📦",
    "333": "Delivered ✅",
}

BUSINESS_CONTEXT = """
=== NORTH STAR SUPPORT BOT — SYSTEM CONTEXT ===

You are "North Star", the friendly customer support chatbot for an outdoor 
apparel and camping gear e-commerce store. 

PERSONA:
- Name: North Star Support Bot
- Tone: Friendly, helpful, outdoorsy, concise
- Audience: North American outdoor consumers
- Use trail/adventure related language and occasional relevant emojis 🌲🏕️⭐

CAPABILITIES YOU HANDLE:
1. ORDER TRACKING
   - Ask for the order number if not provided
   - Use the order status lookup results provided to you
   - Order #111 → Shipped, arriving tomorrow
   - Order #222 → Processing, ships in 24 hours  
   - Order #333 → Delivered (ask a follow-up if everything arrived okay)
   - Any other number → politely say it wasn't found, ask to double-check

2. RETURNS & EXCHANGES
   - 30-day return window, items must be unused, in original packaging
   - Returns link: https://northstar.example.com/returns
   - Explain clearly and offer next steps

3. PRODUCT RECOMMENDATIONS
   - Ask 1-2 clarifying questions (activity type, season/conditions)
   - Recommend a relevant product category with specific examples
   - Categories: Hiking Gear, Camping Gear, Climbing, Apparel, Water Sports
   - Shop link: https://northstar.example.com/shop

4. SHIPPING INFO
   - Standard: 3-5 business days
   - Expedited: 1-2 business days

5. HUMAN HANDOFF
   - If asked to speak to a human/agent, transition gracefully
   - Provide: support@northstar.example.com, avg wait ~2 minutes
   - Stay warm and reassuring

FALLBACK BEHAVIOR:
- If you don't understand, say so clearly
- Always offer the main options: order tracking, returns, product recs, live agent
- Never make up order data, policies, or products not listed above

CONVERSATION STYLE:
- Keep responses concise but warm
- Use bullet points for lists
- After resolving a query, ask if there's anything else you can help with
- Always stay in character as North Star Support Bot
"""


# ─────────────────────────────────────────────────────────────────
#  Order lookup tool (called before LLM when order # detected)
# ─────────────────────────────────────────────────────────────────
def lookup_order(user_input: str) -> str | None:
    """Extract order number from text and return status if found."""
    match = re.search(r'\b(\d{3,})\b', user_input)
    if match:
        num = match.group(1)
        if num in ORDER_DB:
            return f"[ORDER LOOKUP RESULT] Order #{num} status: {ORDER_DB[num]}"
        else:
            return f"[ORDER LOOKUP RESULT] Order #{num} was NOT found in the system."
    return None


# ─────────────────────────────────────────────────────────────────
#  Build the LangChain chain
# ─────────────────────────────────────────────────────────────────
def build_chain(api_key: str):
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0.4,
        max_output_tokens=512,
    )

    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=BUSINESS_CONTEXT),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{input}"),
    ])

    chain = prompt | llm
    return chain


# ─────────────────────────────────────────────────────────────────
#  Chatbot session manager
# ─────────────────────────────────────────────────────────────────
class NorthStarBot:
    def __init__(self, api_key: str):
        self.session_id = "user_session_1"
        chain = build_chain(api_key)

        # Define the LangGraph StateGraph workflow
        def call_model(state: BotState):
            history = state["messages"][:-1]
            last_message = state["messages"][-1]
            response = chain.invoke({"history": history, "input": last_message.content})
            return {"messages": [response]}

        workflow = StateGraph(BotState)
        workflow.add_node("agent", call_model)
        workflow.add_edge(START, "agent")

        self.memory = MemorySaver()
        self.app = workflow.compile(checkpointer=self.memory)

    def chat(self, user_input: str) -> str:
        # Inject order lookup data when an order number is mentioned
        order_info = lookup_order(user_input)
        if order_info:
            enriched_input = f"{user_input}\n\n{order_info}"
        else:
            enriched_input = user_input

        config = {"configurable": {"thread_id": self.session_id}}
        state_output = self.app.invoke(
            {"messages": [HumanMessage(content=enriched_input)]},
            config=config,
        )
        return state_output["messages"][-1].content

    def reset(self):
        self.memory.delete_thread(self.session_id)


# ─────────────────────────────────────────────────────────────────
#  CLI runner
# ─────────────────────────────────────────────────────────────────
def main():
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        print("\n⚠️  No GOOGLE_API_KEY found.")
        api_key = input("   Paste your Google Gemini API key: ").strip()
        if not api_key:
            print("API key required. Get one at https://aistudio.google.com/app/apikey")
            return

    print("\n" + "=" * 58)
    print("   🌟  North Star Support Bot  (LangChain + Gemini)")
    print("   Outdoor Apparel & Camping Gear")
    print("=" * 58)
    print("Commands: 'reset' to clear history | 'quit' to exit\n")

    bot = NorthStarBot(api_key)

    # Opening greeting
    greeting = bot.chat("Hello! I just arrived at the site.")
    print(f"Bot: {greeting}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBot: Happy trails! 🌲⭐")
            break

        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit"}:
            print("Bot: Happy trails! 🌲⭐")
            break
        if user_input.lower() == "reset":
            bot.reset()
            print("Bot: Conversation cleared! Starting fresh 🌟\n")
            continue

        try:
            reply = bot.chat(user_input)
            print(f"\nBot: {reply}\n")
        except Exception as e:
            print(f"\n⚠️  Error: {e}")
            print("Check your API key and internet connection.\n")


if __name__ == "__main__":
    main()







