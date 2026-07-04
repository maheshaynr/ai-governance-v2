import streamlit as st
import requests
import json

st.set_page_config(page_title="AI Governance Shield", layout="wide")

# Inject Custom CSS for Professional Enterprise Look
st.markdown("""
<style>
    /* Clean, professional styling */
    .stTextInput>div>div>input, .stNumberInput>div>div>input {
        border-radius: 4px;
        border: 1px solid #d0d7de;
        padding: 8px 12px;
    }
    .rule-card {
        background-color: #f6f8fa;
        border: 1px solid #d0d7de;
        border-radius: 6px;
        padding: 12px;
        margin-bottom: 12px;
        box-shadow: 0 1px 3px rgba(27,31,35,0.04);
    }
    .rule-title {
        font-weight: 600;
        color: #24292f;
        margin-bottom: 4px;
    }
    .rule-meta {
        font-size: 0.85em;
        color: #57606a;
    }
    /* Simple Login Form Styling */
    .login-box {
        max-width: 400px;
        margin: 50px auto;
        padding: 30px;
        border: 1px solid #eaecef;
        border-radius: 8px;
        background-color: #ffffff;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
</style>
""", unsafe_allow_html=True)

# Session State for Admin Auth & Editing
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "editing_rule" not in st.session_state:
    st.session_state["editing_rule"] = None

# Top Navigation (instead of sidebar)
st.title("🛡️ Enterprise AI Governance v1.0")
page = st.radio("Navigation Pane", ["Testing Dashboard", "Admin Configuration"], horizontal=True, label_visibility="collapsed")
st.markdown("---")

# --- PAGE 1: TESTING DASHBOARD ---
if page == "Testing Dashboard":
    st.header("Egress Shield (Client)")
    st.markdown("Test the **Universal Output Guardrail** against Database Queries and AI Hallucinations.")
    
    tab1, tab2, tab3 = st.tabs(["Test 2: DB Cohort Lookup", "Test 3: AI Hallucination Shield", "Test 1: False Positive Math Check"])
    
    with tab1:
        st.subheader("Test Case 2: Secure Database Retrieval")
        st.markdown("Retrieves raw sensitive data from SQLite and passes it through the Egress Guardrail.")
        cust_id = st.number_input("Enter Customer ID (Try 101):", min_value=100, max_value=999, value=101)
        if st.button("Query Database"):
            with st.spinner("Querying backend..."):
                try:
                    res = requests.post("http://localhost:8000/query_db", json={"customer_id": cust_id})
                    if res.status_code == 200:
                        st.success(res.json()["masked_output"])
                    else:
                        st.error("API Error")
                except Exception as e:
                    st.error("Failed to connect to backend. Is uvicorn running?")
    
    with tab2:
        st.subheader("Test Case 3: AI Hallucination Shield")
        st.markdown("Simulates an internal AI model accidentally outputting sensitive data.")
        ai_text = st.text_area("Simulated AI Output:", value="Please use the corporate credit card 4111-2222-3333-4444 and reference PAN Card ABCPD1234F.")
        if st.button("Pass AI Output through Guardrail"):
            with st.spinner("Scanning AI output..."):
                try:
                    res = requests.post("http://localhost:8000/govern_ai", json={"text": ai_text})
                    if res.status_code == 200:
                        st.success(res.json()["masked_output"])
                except:
                    st.error("Connection failed.")
    
    with tab3:
        st.subheader("Test Case 1: The False Positive (Aadhaar Checksum)")
        st.markdown("Tests a 12-digit order number that looks like Aadhaar but fails the Verhoeff math.")
        fake_order = st.text_input("Simulated Chat Input:", value="Cancel order number 9999 4105 7059.")
        st.caption("Note: Ends in 9 (invalid mathematical checksum). Will NOT be masked.")
        if st.button("Scan False Positive"):
            with st.spinner("Scanning..."):
                try:
                    res = requests.post("http://localhost:8000/govern_ai", json={"text": fake_order})
                    if res.status_code == 200:
                        st.info(res.json()["masked_output"])
                except:
                    st.error("Connection failed.")

# --- PAGE 2: ADMIN CONFIGURATION ---
elif page == "Admin Configuration":
    
    # 1. Login Gate
    if not st.session_state["logged_in"]:
        st.markdown("<div class='login-box'>", unsafe_allow_html=True)
        st.subheader("Admin Login Required")
        st.info("Use admin / admin to test the PoC.")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            if username == "admin" and password == "admin":
                st.session_state["logged_in"] = True
                st.rerun()
            else:
                st.error("Invalid credentials.")
        st.markdown("</div>", unsafe_allow_html=True)
    
    # 2. Main Configuration Layout
    else:
        st.button("Logout", on_click=lambda: st.session_state.update({"logged_in": False}))
        
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.subheader("Existing Rules")
            
            # Use a scrollable container for the rules list
            with st.container(height=500):
                try:
                    res = requests.get("http://localhost:8000/rules")
                    if res.status_code == 200:
                        rules = res.json().get("rules", [])
                        for i, rule in enumerate(rules):
                            with st.container():
                                st.markdown(f"""
                                <div class="rule-card">
                                    <div class="rule-title">#{i+1}: {rule['name']}</div>
                                    <div class="rule-meta">Entity: {rule['entity']}</div>
                                </div>
                                """, unsafe_allow_html=True)
                                # Button to enter edit mode
                                if st.button(f"Edit ##{i+1}", key=f"edit_{rule['name']}"):
                                    st.session_state["editing_rule"] = rule
                                    st.rerun()
                    else:
                        st.error("Could not fetch rules from backend.")
                except Exception as e:
                    st.warning("Backend API is unreachable.")
                
        with col2:
            # Determine if we are editing or adding
            is_editing = st.session_state.get("editing_rule") is not None
            current_rule = st.session_state.get("editing_rule", {})
            
            st.subheader("Edit Rule" if is_editing else "Add New Rule")
            
            if is_editing:
                if st.button("Cancel Edit"):
                    st.session_state["editing_rule"] = None
                    st.rerun()
            
            with st.form("rule_form"):
                new_alias = st.text_input("Rule Alias Name", 
                                          value=current_rule.get("name", ""),
                                          help="A human-readable name for this rule (e.g., 'Corporate_Credit_Card_v2').")
                
                new_entity = st.text_input("Entity Class", 
                                           value=current_rule.get("entity", ""),
                                           help="The Presidio tag used to mask the data (e.g., 'CREDIT_CARD', 'INTERNAL_PROJECT'). The output will be replaced with <ENTITY_CLASS>.")
                
                new_regex = st.text_input("Regex Pattern", 
                                          value=current_rule.get("regex", ""),
                                          help="The mathematical regular expression that matches the sensitive data. Make sure to use word boundaries (\\b) to avoid partial matches.")
                
                new_score = st.slider("Confidence Score", min_value=0.0, max_value=1.0, 
                                      value=current_rule.get("score", 0.85), step=0.05,
                                      help="How confident the AI should be when making this match. A lower score (0.4) might catch more data but cause false positives. A high score (0.9) requires exact matches.")
                
                submit_label = "Update Rule" if is_editing else "Add New Rule"
                submitted = st.form_submit_button(submit_label)
                
                if submitted:
                    if not new_alias or not new_entity or not new_regex:
                        st.error("All fields are required.")
                    else:
                        payload = {
                            "name": new_alias,
                            "entity": new_entity,
                            "regex": new_regex,
                            "score": new_score
                        }
                        
                        try:
                            if is_editing:
                                payload["original_name"] = current_rule.get("name")
                                post_res = requests.post("http://localhost:8000/update_rule", json=payload)
                            else:
                                post_res = requests.post("http://localhost:8000/add_rule", json=payload)
                                
                            if post_res.status_code == 200:
                                st.success(f"Rule successfully {'updated' if is_editing else 'added'} and hot-reloaded!")
                                st.session_state["editing_rule"] = None
                                # St.rerun immediately clears success message, so we just let it stay for a bit
                                # Wait, we can just clear the session state.
                            else:
                                st.error("Failed to save rule.")
                        except:
                            st.error("Failed to connect to backend.")
