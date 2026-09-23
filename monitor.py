"""
Bot que revisa si vuelve a haber stock en varias tiendas
y avisa por Telegram. Se ejecuta solo en GitHub cada 10 minutos.
No hace falta tocar este archivo: las tiendas se configuran en tiendas.json
"""
import json
import os

import requests
from bs4 import BeautifulSoup
from curl_cffi import requests as navegador

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ARCHIVO_TIENDAS = "tiendas.json"
ARCHIVO_ESTADO = "estado.json"
FALLOS_ANTES_DE_AVISAR = 3  # 3 fallos seguidos = unos 30 minutos sin poder revisar

CABECERAS = {"Accept-Language": "es-ES,es;q=0.9"}


def enviar_telegram(mensaje):
    if not TOKEN or not CHAT_ID:
        print("ERROR TELEGRAM: faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID en los secretos de GitHub")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN.strip()}/sendMessage",
            data={"chat_id": CHAT_ID.strip(), "text": mensaje, "disable_web_page_preview": True},
            timeout=20,
        )
        if r.ok:
            print("Telegram: mensaje enviado")
        else:
            print(f"ERROR TELEGRAM ({r.status_code}): {r.text}")
    except Exception as error:
        print(f"ERROR TELEGRAM: {error}")


def cargar_json(ruta, por_defecto):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return por_defecto


def leer_texto_pagina(url):
    # Visitamos la página haciéndonos pasar por Google Chrome
    # para que las tiendas no bloqueen al bot
    respuesta = navegador.get(url, headers=CABECERAS, impersonate="chrome", timeout=30)
    respuesta.raise_for_status()
    sopa = BeautifulSoup(respuesta.text, "html.parser")
    for etiqueta in sopa(["script", "style", "noscript"]):
        etiqueta.decompose()
    return " ".join(sopa.get_text(" ").split()).lower()


def hay_stock(tienda):
    texto = leer_texto_pagina(tienda["url"])

    # Seguridad: si no aparece el nombre del producto, la tienda nos ha
    # mostrado otra cosa (bloqueo, error...). No lo damos por bueno.
    comprobar = tienda.get("comprobar", "").lower()
    if comprobar and comprobar not in texto:
        raise ValueError("La página no muestra el producto (posible bloqueo de la tienda)")

    if tienda.get("texto_disponible"):
        return tienda["texto_disponible"].lower() in texto
    return tienda["texto_agotado"].lower() not in texto


def main():
    tiendas = cargar_json(ARCHIVO_TIENDAS, [])
    estado = cargar_json(ARCHIVO_ESTADO, {})
    stock_guardado = estado.setdefault("stock", {})
    fallos = estado.setdefault("fallos", {})

    for tienda in tiendas:
        nombre = tienda["nombre"]
        url = tienda["url"]

        try:
            stock = hay_stock(tienda)
        except Exception as error:
            fallos[url] = fallos.get(url, 0) + 1
            print(f"[{nombre}] No se pudo revisar ({fallos[url]} seguidos): {error}")
            if fallos[url] == FALLOS_ANTES_DE_AVISAR:
                enviar_telegram(
                    f"⚠️ No consigo revisar {nombre} desde hace un rato.\n"
                    f"Motivo: {error}\nSeguiré intentándolo.\n{url}"
                )
            continue

        if fallos.get(url, 0) >= FALLOS_ANTES_DE_AVISAR:
            enviar_telegram(f"👍 Vuelvo a poder revisar {nombre}.")
        fallos[url] = 0

        anterior = stock_guardado.get(url)
        print(f"[{nombre}] stock ahora: {stock} | antes: {anterior}")

        if anterior is None:
            situacion = "HAY STOCK ✅" if stock else "agotado ❌"
            enviar_telegram(f"👀 Empiezo a vigilar {nombre}.\nAhora mismo: {situacion}\n{url}")
        elif stock and not anterior:
            enviar_telegram(f"🚨🚨 ¡{nombre} VUELVE A TENER STOCK! 🚨🚨\n{url}")
        elif not stock and anterior:
            enviar_telegram(f"❌ {nombre} se ha vuelto a agotar.\n{url}")

        stock_guardado[url] = stock

    # Si lo lanzas a mano desde GitHub, te manda un resumen para comprobar que funciona
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        lineas = []
        for tienda in tiendas:
            valor = stock_guardado.get(tienda["url"])
            if fallos.get(tienda["url"], 0) > 0:
                situacion = "⚠️ no se pudo revisar"
            elif valor:
                situacion = "HAY STOCK ✅"
            else:
                situacion = "agotado ❌"
            lineas.append(f"• {tienda['nombre']}: {situacion}")
        enviar_telegram("🧪 Revisión manual\n" + "\n".join(lineas))

    with open(ARCHIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
