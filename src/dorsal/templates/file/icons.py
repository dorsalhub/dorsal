ICON_MAP = {
    "application/pdf": """
<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
  <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
</svg>
""",
    "image": """
<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
  <path stroke-linecap="round" stroke-linejoin="round" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 0-1.5-1.5H3.75A1.5 1.5 0 0 0 2.25 6v12a1.5 1.5 0 0 0 1.5 1.5Zm10.5-11.25h.008v.008h-.008V8.25Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z" />
</svg>
""",
    "audio": """
<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
  <path stroke-linecap="round" stroke-linejoin="round" d="M9 9V4.5M9 9l-3.375-3.375M9 9l3.375-3.375m0 0L15.75 9m-2.375-3.375L15.75 3m-3.375 3.375L9 3m2.375 3.375L12 9m-3 9v-2.25m6 2.25v-2.25m0 0l-3-3m3 3l3-3m-3-3v-2.25m6 2.25V15m0 0l-3-3m3 3l3-3m-3-3V9.75M12 15v2.25m0 0l-3-3m3 3l3-3m-3-3v-2.25m-6 2.25V15m0 0l3-3m-3 3l-3-3m3-3V9.75" />
</svg>
""",
    "video": """
<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
  <path stroke-linecap="round" stroke-linejoin="round" d="m15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9A2.25 2.25 0 0 0 13.5 5.25h-9a2.25 2.25 0 0 0-2.25 2.25v9A2.25 2.25 0 0 0 4.5 18.75Z" />
</svg>
""",
    "default": """
<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
  <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m.75 12V9a.75.75 0 0 0-.75-.75H5.625a.75.75 0 0 0-.75.75v6.75a.75.75 0 0 0 .75.75h3.75a.75.75 0 0 0 .75-.75Z" />
</svg>
""",
}


def get_media_type_icon(media_type: str) -> str:
    """Returns an SVG icon string for a given media type."""
    if media_type in ICON_MAP:
        return ICON_MAP[media_type]

    main_type = media_type.split("/")[0]
    if main_type in ICON_MAP:
        return ICON_MAP[main_type]

    return ICON_MAP["default"]
