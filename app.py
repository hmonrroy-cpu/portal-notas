import streamlit as st
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

st.set_page_config(
    page_title="Portal de Calificaciones",
    page_icon="🎓",
    layout="centered"
)

st.markdown("""
    <style>
    .block-container { padding-top: 2rem; max-width: 650px; }
    div[data-testid="stMetricValue"] { font-size: 1.5rem; }
    </style>
""", unsafe_allow_html=True)

def normalizar_rut(texto):
    if not texto:
        return ""
    return ''.join(c for c in str(texto).upper() if c.isalnum())

def obtener_pin_defecto(rut_normalizado):
    if len(rut_normalizado) >= 5:
        return rut_normalizado[-5:-1]
    return rut_normalizado

@st.cache_data(ttl=900)
def cargar_datos_desde_drive():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly"
    ]
    creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=scopes)
    gc = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)

    folder_id = st.secrets["FOLDER_ID"]
    
    def listar_archivos(f_id):
        archivos = []
        q_files = f"'{f_id}' in parents and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
        res_files = drive_service.files().list(q=q_files, fields="files(id, name)").execute()
        archivos.extend(res_files.get('files', []))
        
        q_folders = f"'{f_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        res_folders = drive_service.files().list(q=q_folders, fields="files(id, name)").execute()
        for subf in res_folders.get('files', []):
            archivos.extend(listar_archivos(subf['id']))
        return archivos

    todos_los_archivos = listar_archivos(folder_id)
    alumnos = {}
    cols_base = ["n°", "rut", "apellido paterno", "apellido materno", "nombres", "correo", "email"]

    for arch in todos_los_archivos:
        nombre_hoja = arch['name']
        if "CONSOLIDADO" in nombre_hoja.upper():
            continue

        es_practico = "PRACTICO" in nombre_hoja.upper()
        categoria = "Práctico" if es_practico else "Teórico"
        nombre_limpio = (
            nombre_hoja.replace("2026_C2_NOTAS PARA DOCENTES_", "")
                       .replace("TEORICO_", "")
                       .replace("PRACTICO_", "")
                       .strip()
        )

        try:
            sh = gc.open_by_key(arch['id']).sheet1
            filas = sh.get_all_values()
            if len(filas) < 2:
                continue

            headers = filas[0]
            idx_rut = -1
            idx_correo = -1
            idx_nom = -1
            idx_ap_pat = -1
            idx_clave = -1
            cols_eval = []

            for col_idx, h in enumerate(headers):
                hl = str(h).strip().lower()
                if hl == "rut": idx_rut = col_idx
                elif "correo" in hl or "email" in hl: idx_correo = col_idx
                elif "nombres" in hl: idx_nom = col_idx
                elif "apellido paterno" in hl: idx_ap_pat = col_idx
                elif "clave" in hl or "pin" in hl: idx_clave = col_idx
                elif hl not in cols_base and hl != "":
                    cols_eval.append((col_idx, str(h).strip()))

            for fila in filas[1:]:
                if idx_rut == -1 or len(fila) <= idx_rut:
                    continue
                
                rut_raw = fila[idx_rut]
                rut_norm = normalizar_rut(rut_raw)
                if not rut_norm:
                    continue

                if rut_norm not in alumnos:
                    nombre_completo = ""
                    if idx_nom != -1 and idx_ap_pat != -1 and len(fila) > max(idx_nom, idx_ap_pat):
                        nombre_completo = f"{fila[idx_nom].strip()} {fila[idx_ap_pat].strip()}"
                    
                    email_alumno = fila[idx_correo].strip().lower() if idx_correo != -1 and len(fila) > idx_correo else ""
                    pin_final = (
                        fila[idx_clave].strip() 
                        if idx_clave != -1 and len(fila) > idx_clave and fila[idx_clave] != "" 
                        else obtener_pin_defecto(rut_norm)
                    )

                    alumnos[rut_norm] = {
                        "rut_completo": rut_raw,
                        "nombre": nombre_completo,
                        "correo": email_alumno,
                        "pin": pin_final,
                        "notas": []
                    }

                detalles_materia = []
                for c_idx, c_name in cols_eval:
                    if c_idx < len(fila):
                        val = str(fila[c_idx]).strip().replace(",", ".")
                        if val not in ["", "0", "0.0", "p", "P"]:
                            detalles_materia.append({"item": c_name, "nota": val})

                if detalles_materia:
                    alumnos[rut_norm]["notas"].append({
                        "materia": nombre_limpio,
                        "tipo": categoria,
                        "detalles": detalles_materia
                    })

        except Exception:
            continue

    return alumnos

if "user" not in st.session_state:
    st.session_state.user = None

if not st.session_state.user:
    st.markdown("<h2 style='text-align: center;'>Portal de Calificaciones</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #64748b;'>Consulta tu registro académico</p>", unsafe_allow_html=True)
    
    with st.form("form_login"):
        user_input = st.text_input("RUT o Correo UC", placeholder="Ej: 20428599-3 o alumno@uc.cl")
        pin_input = st.text_input("PIN / Clave", type="password", placeholder="••••")
        btn_login = st.form_submit_button("Consultar notas", use_container_width=True)

        if btn_login:
            if not user_input or not pin_input:
                st.warning("Por favor completa ambos campos.")
            else:
                with st.spinner("Cargando notas del curso..."):
                    db_alumnos = cargar_datos_desde_drive()
                
                ingreso_norm = normalizar_rut(user_input)
                ingreso_correo = user_input.strip().lower()
                
                alumno_encontrado = None
                for rut_k, datos in db_alumnos.items():
                    if rut_k == ingreso_norm or datos["correo"] == ingreso_correo:
                        alumno_encontrado = datos
                        break

                if alumno_encontrado:
                    if alumno_encontrado["pin"] == pin_input.strip():
                        st.session_state.user = alumno_encontrado
                        st.rerun()
                    else:
                        st.error("PIN o clave incorrecta.")
                else:
                    st.error("No se encontró ningún estudiante con ese identificador.")

else:
    u = st.session_state.user
    c_izq, c_der = st.columns([3, 1])
    with c_izq:
        st.subheader(f"👋 {u['nombre']}")
        st.caption(f"RUT: {u['rut_completo']} | {u['correo']}")
    with c_der:
        if st.button("Cerrar sesión", use_container_width=True):
            st.session_state.user = None
            st.rerun()

    st.markdown("---")

    if not u["notas"]:
        st.info("No hay calificaciones registradas para tu usuario en este momento.")
    else:
        tab_teorico, tab_practico = st.tabs(["📚 Módulos Teóricos", "🏥 Rotaciones Prácticas"])

        def mostrar_bloque(lista):
            if not lista:
                st.write("Sin registros disponibles en esta categoría.")
                return
            for m in lista:
                with st.expander(f"**{m['materia']}**", expanded=True):
                    for d in m["detalles"]:
                        col1, col2 = st.columns([3, 1])
                        col1.write(f"• {d['item']}")
                        try:
                            val_num = float(d['nota'])
                            color = "green" if val_num >= 4.0 else "red"
                            col2.markdown(f":{color}[**{d['nota']}**]")
                        except:
                            col2.markdown(f"**{d['nota']}**")

        with tab_teorico:
            mostrar_bloque([n for n in u["notas"] if n["tipo"] == "Teórico"])

        with tab_practico:
            mostrar_bloque([n for n in u["notas"] if n["tipo"] == "Práctico"])
