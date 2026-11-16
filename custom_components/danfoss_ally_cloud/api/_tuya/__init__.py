"""Pile Tuya « voie 1a » vendue depuis danfoss-ally-mcp (reverse validé en réel).

Trois modules purs (stdlib + requests + pycryptodome), sans l'app ni frida :
- ``sign`` : signature HMAC-SHA256 du canonical.
- ``postdata`` : chiffrement AES-GCM du postData (requête et réponse).
- ``http`` : client HTTP bas niveau des méthodes ``m.*`` et flux de login.

À extraire à terme en bibliothèque partagée avec le connecteur MCP (roadmap v0.6).
Ne jamais logguer sign_key, sid, ecode ni chKey.
"""
