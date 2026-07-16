"""
pages/05_International_Jobs.py

Streamlit page — International Job Search for Bindu.
Shows country selector, triggers the international scraper,
displays results in a filterable table grouped by country.

Navigate to it via the Streamlit sidebar: “International Jobs”

FIX (v2): All st.* calls moved inside main() so nothing executes at
import/module-load time.  The old code called st.columns() at module
level which caused Streamlit to render raw DeltaGenerator repr objects
into the page instead of actual widgets.
"""
import time
import requests
import streamlit as st
import pandas as pd

BACKEND = "http://127.0.0.1:8000/api/v1"

ALL_COUNTRIES = ["UAE", "Singapore", "Australia", "Canada", "New Zealand", "India", "Remote"]


def main():
    st.title("🌍 International Job Search")
    st.caption(
        "Find supply chain & logistics roles in UAE, Singapore, Australia, Canada, "
        "New Zealand, India and Remote — tailored for a UK master’s graduate."
    )

    # -----------------------------------------------------------------------
    # Sidebar — country selector + visa notes
    # -----------------------------------------------------------------------

    st.sidebar.header("🏓 Target Countries")

    try:
        meta_resp = requests.get(f"{BACKEND}/jobs/international/countries", timeout=5)
        country_meta = {c["name"]: c for c in meta_resp.json()}
    except Exception:
        country_meta = {}

    selected_countries = st.sidebar.multiselect(
        "Select countries to search",
        options=ALL_COUNTRIES,
        default=["UAE", "Singapore", "Australia", "Canada", "Remote"],
    )

    if selected_countries and country_meta:
        with st.sidebar.expander("📝 Visa & Work Permit Notes", expanded=False):
            for c in selected_countries:
                meta = country_meta.get(c, {})
                if meta.get("visa_notes"):
                    st.markdown(f"**{c}:** {meta['visa_notes']}")

    # -----------------------------------------------------------------------
    # Keyword input
    # -----------------------------------------------------------------------

    st.subheader("🔍 Search Settings")
    col1, col2 = st.columns(2)
    with col1:
        keyword_input = st.text_input(
            "Job keywords (comma-separated)",
            value="graduate supply chain analyst, demand planning analyst, operations analyst, procurement analyst, logistics analyst",
        )
    with col2:
        visa_filter = st.checkbox("🔵 Show only visa/relocation-sponsored roles", value=False)

    keywords = [k.strip() for k in keyword_input.split(",") if k.strip()]

    # -----------------------------------------------------------------------
    # Search button
    # -----------------------------------------------------------------------

    if st.button("🚀 Search International Jobs", type="primary", disabled=not selected_countries):
        if not selected_countries:
            st.warning("Please select at least one country.")
        else:
            with st.spinner(f"Searching {', '.join(selected_countries)}... (usually 30–90 seconds)"):
                try:
                    resp = requests.post(
                        f"{BACKEND}/jobs/international/search",
                        json={"keywords": keywords, "countries": selected_countries},
                        timeout=180,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    jobs = data.get("jobs", [])
                    st.session_state["intl_jobs"] = jobs
                    st.session_state["intl_meta"] = {
                        "total":          data.get("total", 0),
                        "by_country":     data.get("by_country", {}),
                        "visa_sponsored": data.get("visa_sponsored", 0),
                    }
                    st.success(f"✅ Found **{data.get('total', 0)} jobs** across {len(data.get('by_country', {}))} countries")
                except requests.exceptions.Timeout:
                    st.error("⏱️ Request timed out. Try fewer countries or keywords.")
                except Exception as e:
                    st.error(f"❌ Search failed: {e}")

    # -----------------------------------------------------------------------
    # Results
    # -----------------------------------------------------------------------

    if "intl_jobs" in st.session_state and st.session_state["intl_jobs"]:
        jobs = st.session_state["intl_jobs"]
        meta = st.session_state.get("intl_meta", {})

        m1, m2, m3 = st.columns(3)
        m1.metric("Total Jobs Found",      meta.get("total", len(jobs)))
        m2.metric("Visa/Relocation Roles", meta.get("visa_sponsored", 0))
        m3.metric("Countries Covered",     len(meta.get("by_country", {})))

        if meta.get("by_country"):
            st.subheader("📊 Jobs by Country")
            bc = meta["by_country"]
            chart_df = pd.DataFrame({"Country": list(bc.keys()), "Jobs": list(bc.values())})
            st.bar_chart(chart_df.set_index("Country"))

        df = pd.DataFrame(jobs)

        if visa_filter and "visa_sponsored" in df.columns:
            df = df[df["visa_sponsored"] == True]  # noqa: E712

        if "country" in df.columns:
            country_tab_filter = st.selectbox(
                "Filter by country", ["All"] + sorted(df["country"].unique().tolist())
            )
            if country_tab_filter != "All":
                df = df[df["country"] == country_tab_filter]

        display_cols = [c for c in ["title", "company", "location", "country", "salary",
                                    "match_score", "visa_sponsored", "source", "url"] if c in df.columns]
        df_display = df[display_cols].copy()
        if "match_score" in df_display.columns:
            df_display = df_display.sort_values("match_score", ascending=False)

        st.subheader(f"💼 {len(df_display)} Roles")
        st.dataframe(df_display, use_container_width=True)

        csv = df_display.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download as CSV",
            data=csv,
            file_name=f"international_jobs_{time.strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )

    elif "intl_jobs" in st.session_state:
        st.info("🔍 No jobs found. Try different keywords or add more countries.")
    else:
        st.info("↑ Configure your search above and click **Search International Jobs** to begin.")

    # -----------------------------------------------------------------------
    # Deep scan (background)
    # -----------------------------------------------------------------------

    with st.expander("🔬 Full Deep Scan (all terms × all countries — runs in background)"):
        st.caption(
            "This triggers the full scraper across all 10 search terms and all 7 countries. "
            "Takes 5–10 minutes and saves to `exports/jobs_international_<timestamp>.csv`."
        )
        if st.button("🔥 Start Full Deep Scan"):
            try:
                r = requests.post(f"{BACKEND}/jobs/international/full", timeout=10)
                st.success(r.json().get("message", "Deep scan started."))
            except Exception as e:
                st.error(f"Failed to start deep scan: {e}")


main()
