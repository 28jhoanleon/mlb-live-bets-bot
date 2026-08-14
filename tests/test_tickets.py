"""Tests de separación de apuestas (tickets).

Bug real que motivó esto: el usuario mandó capturas con 4 tarjetas SGM
distintas (partidos distintos, cuotas distintas) y el bot las fusionó en
UNA sola combinada de 11 legs. Son apuestas separadas: cada una se gana
o se pierde por su cuenta.
"""
from app.analysis.tickets import merge_tickets, normalize, to_storage


def _leg(player, market="Hits + Runs + RBIs", line="Over 0.5", match=None):
    leg = {"player": player, "market": market, "line": line}
    if match:
        leg["match"] = match
    return leg


class TestNormalizacion:
    def test_formato_nuevo_respeta_los_tickets(self):
        analysis = {
            "is_live": True,
            "bets": [
                {"match": "A vs B", "total_odds": "2.95", "legs": [_leg("Uno")]},
                {"match": "C vs D", "total_odds": "2.80", "legs": [_leg("Dos")]},
            ],
        }
        tickets = normalize(analysis)
        assert len(tickets) == 2
        assert tickets[0]["total_odds"] == "2.95"

    def test_formato_viejo_separa_por_partido(self):
        """Legs de partidos distintos nunca son la misma apuesta."""
        analysis = {
            "is_live": True,
            "legs": [
                _leg("Keller", match="Pirates vs Diamondbacks"),
                _leg("Kelly", match="Pirates vs Diamondbacks"),
                _leg("Cowser", match="Tigers vs Orioles"),
                _leg("Abrams", match="Nationals vs Blue Jays"),
            ],
        }
        tickets = normalize(analysis)
        assert len(tickets) == 3
        assert sorted(len(t["legs"]) for t in tickets) == [1, 1, 2]

    def test_ticket_sin_legs_se_descarta(self):
        analysis = {"bets": [{"match": "A vs B", "legs": []}]}
        assert normalize(analysis) == []

    def test_analisis_vacio_no_rompe(self):
        assert normalize({}) == []
        assert normalize({"legs": []}) == []


class TestFusionEntreCapturas:
    def test_mismo_ticket_en_dos_capturas_se_une(self):
        """Al scrollear una combinada larga, dos capturas muestran partes
        del mismo ticket: hay que unirlas, no duplicarlas."""
        foto1 = [{"match": "A vs B", "total_odds": "2.95", "legs": [_leg("Uno"), _leg("Dos")]}]
        foto2 = [{"match": "A vs B", "total_odds": "2.95", "legs": [_leg("Dos"), _leg("Tres")]}]

        tickets = merge_tickets([foto1, foto2])

        assert len(tickets) == 1
        assert len(tickets[0]["legs"]) == 3  # Dos no se duplicó

    def test_tickets_distintos_quedan_separados(self):
        foto1 = [{"match": "A vs B", "total_odds": "2.95", "legs": [_leg("Uno")]}]
        foto2 = [{"match": "C vs D", "total_odds": "2.80", "legs": [_leg("Dos")]}]

        assert len(merge_tickets([foto1, foto2])) == 2

    def test_mismo_partido_distinta_cuota_son_apuestas_distintas(self):
        """Se pueden tener dos SGM del mismo partido: son tickets
        distintos y se distinguen por su cuota total."""
        foto1 = [{"match": "A vs B", "total_odds": "2.95", "legs": [_leg("Uno")]}]
        foto2 = [{"match": "A vs B", "total_odds": "5.60", "legs": [_leg("Dos")]}]

        assert len(merge_tickets([foto1, foto2])) == 2

    def test_orden_de_equipos_no_parte_el_ticket(self):
        """'Pirates vs Diamondbacks' y 'Diamondbacks @ Pirates' son el
        mismo partido."""
        foto1 = [{"match": "Pirates vs Diamondbacks", "total_odds": "2.95", "legs": [_leg("Uno")]}]
        foto2 = [{"match": "Diamondbacks @ Pirates", "total_odds": "2.95", "legs": [_leg("Dos")]}]

        assert len(merge_tickets([foto1, foto2])) == 1

    def test_conserva_el_orden_de_aparicion(self):
        foto1 = [{"match": "A vs B", "total_odds": "1", "legs": [_leg("Primero")]}]
        foto2 = [{"match": "C vs D", "total_odds": "2", "legs": [_leg("Segundo")]}]

        tickets = merge_tickets([foto1, foto2])
        assert tickets[0]["legs"][0]["player"] == "Primero"


class TestAcumulacionEntreEnvios:
    """Las capturas se acumulan sin que el usuario escriba nada."""

    def test_apuesta_nueva_se_suma_sin_pisar_la_anterior(self):
        guardadas = normalize(
            {"bets": [{"match": "A vs B", "total_odds": "2.95", "legs": [_leg("Uno")]}]}
        )
        nuevas = normalize(
            {"bets": [{"match": "C vs D", "total_odds": "2.80", "legs": [_leg("Dos")]}]}
        )

        tickets = merge_tickets([guardadas, nuevas])
        assert len(tickets) == 2

    def test_reenviar_la_misma_captura_no_duplica(self):
        guardadas = normalize(
            {"bets": [{"match": "A vs B", "total_odds": "2.95", "legs": [_leg("Uno")]}]}
        )
        tickets = merge_tickets([guardadas, guardadas])
        assert len(tickets) == 1
        assert len(tickets[0]["legs"]) == 1

    def test_ida_y_vuelta_por_la_base_conserva_los_tickets(self):
        """to_storage + normalize tiene que ser reversible: es lo que
        pasa entre guardar en SQLite y leer para /refresh."""
        original = normalize(
            {
                "bets": [
                    {"match": "A vs B", "total_odds": "2.95", "is_live": True, "legs": [_leg("Uno")]},
                    {"match": "C vs D", "total_odds": "2.80", "is_live": False, "legs": [_leg("Dos")]},
                ]
            }
        )
        recuperado = normalize(to_storage(original))

        assert len(recuperado) == 2
        assert recuperado[0]["total_odds"] == "2.95"
        assert to_storage(original)["is_live"] is True


class TestRedDeSeguridadPorPartido:
    """Bug real: el usuario mandó una captura con 4 apuestas distintas
    (4 tarjetas SGM) y la IA las devolvió como UN solo ticket de 11 legs.
    El resultado fue una 'combinada' inventada, con probabilidad y
    conteo sin sentido.

    La IA puede fallar; el código no debe confiar ciegamente.
    """

    def _leg(self, match, player):
        return {
            "match": match,
            "player": player,
            "market": "Hits + Runs + RBIs",
            "line": "Over 0.5",
        }

    def test_separa_solo_si_no_hay_cuota_total(self):
        """Sin cuota total, legs de varios partidos sugieren que la IA
        mezcló tarjetas vecinas."""
        mezclado = {
            "is_live": True,
            "bets": [
                {
                    "match": "Pirates - Diamondbacks",
                    "total_odds": None,
                    "legs": [
                        self._leg("Pirates - Diamondbacks", "Keller"),
                        self._leg("Pirates - Diamondbacks", "Kelly"),
                        self._leg("Tigers - Orioles", "Cowser"),
                        self._leg("Marlins - Phillies", "Bohm"),
                    ],
                }
            ],
        }

        tickets = normalize(mezclado)

        assert len(tickets) == 3
        por_partido = {t["match"]: len(t["legs"]) for t in tickets}
        assert por_partido["Pirates - Diamondbacks"] == 2
        assert por_partido["Tigers - Orioles"] == 1
        assert por_partido["Marlins - Phillies"] == 1

    def test_no_toca_un_ticket_legitimo_de_un_solo_partido(self):
        """Una combinada del mismo partido (SGM) tiene que quedar intacta."""
        sgm = {
            "is_live": True,
            "bets": [
                {
                    "match": "Pirates - Diamondbacks",
                    "total_odds": "2.95",
                    "legs": [
                        self._leg("Pirates - Diamondbacks", "Keller"),
                        self._leg("Pirates - Diamondbacks", "Kelly"),
                        self._leg("Pirates - Diamondbacks", "Reynolds"),
                    ],
                }
            ],
        }

        tickets = normalize(sgm)

        assert len(tickets) == 1
        assert len(tickets[0]["legs"]) == 3
        assert tickets[0]["total_odds"] == "2.95"

    def test_una_combinada_de_varios_partidos_no_se_parte(self):
        """El caso real que rompía: una combinada de 11 tramos con legs
        de muchos partidos es UN ticket, no once. La cuota total es la
        prueba de que la tarjeta existe."""
        multi = {
            "bets": [
                {
                    "match": "Varios",
                    "total_odds": "23.73",
                    "legs": [
                        self._leg("Phillies - Marlins", "Schwarber"),
                        self._leg("D-backs - Pirates", "Moreno"),
                        self._leg("Nationals - Blue Jays", "Abrams"),
                    ],
                }
            ]
        }

        tickets = normalize(multi)

        assert len(tickets) == 1
        assert len(tickets[0]["legs"]) == 3
        assert tickets[0]["total_odds"] == "23.73"

    def test_descarta_la_cuota_total_al_separar(self):
        """Cuando SÍ hay que separar, la cuota original no aplica a las
        partes: mostrarla sería mentir sobre lo que paga cada una."""
        mezclado = {
            "bets": [
                {
                    "match": "A - B",
                    "total_odds": None,
                    "legs": [self._leg("A - B", "Uno"), self._leg("C - D", "Dos")],
                }
            ]
        }

        for ticket in normalize(mezclado):
            assert ticket["total_odds"] is None

    def test_legs_sin_partido_declarado_no_se_separan(self):
        """Si la IA no informó el partido por leg, no tenemos con qué
        decidir: se deja el ticket como vino en vez de romperlo."""
        sin_match = {
            "bets": [
                {
                    "match": "A - B",
                    "total_odds": "2.10",
                    "legs": [
                        {"player": "Uno", "market": "Hits", "line": "Over 0.5"},
                        {"player": "Dos", "market": "Hits", "line": "Over 0.5"},
                    ],
                }
            ]
        }

        assert len(normalize(sin_match)) == 1


class TestCombinadasDeVariosPartidos:
    """El caso de las apuestas reales del usuario: '11 Multi tramo' con
    cuota 23,73 y '15 Multi tramo' con 68,43. Son DOS tickets, cada uno
    con legs de muchos partidos distintos.

    El error anterior fue asumir que partidos distintos implicaban
    tickets distintos: eso partía una combinada de 11 en varias tarjetas
    sueltas y arruinaba el conteo y la probabilidad.
    """

    def _leg(self, match, player):
        return {"match": match, "player": player, "market": "Hits", "line": "Over 0.5"}

    def test_dos_combinadas_largas_quedan_como_dos_tickets(self):
        captura = {
            "is_live": True,
            "bets": [
                {
                    "match": "Varios",
                    "total_odds": "23.73",
                    "legs": [
                        self._leg("Phillies - Marlins", "Schwarber"),
                        self._leg("D-backs - Pirates", "Moreno"),
                        self._leg("Nationals - Blue Jays", "Abrams"),
                    ],
                },
                {
                    "match": "Varios",
                    "total_odds": "68.43",
                    "legs": [
                        self._leg("Mets - Braves", "Ewing"),
                        self._leg("Tigers - Orioles", "McGonigle"),
                    ],
                },
            ],
        }

        tickets = normalize(captura)

        assert len(tickets) == 2
        assert len(tickets[0]["legs"]) == 3
        assert len(tickets[1]["legs"]) == 2
        assert {t["total_odds"] for t in tickets} == {"23.73", "68.43"}

    def test_conserva_el_numero_de_tramos_declarado(self):
        """Si la casa dice '11 Multi tramo' pero leímos 6, hay que poder
        avisar que la captura quedó incompleta."""
        captura = {
            "bets": [{
                "match": "Varios",
                "total_odds": "23.73",
                "legs_declaradas": 11,
                "legs": [self._leg("A - B", "Uno"), self._leg("C - D", "Dos")],
            }]
        }

        ticket = normalize(captura)[0]

        assert ticket["legs_declaradas"] == 11
        assert len(ticket["legs"]) == 2


class TestCuponConVariosBloques:
    """Bug real: un cupón con cuatro bloques ("Multi apuesta del mismo
    partido"), cada uno con su cuota (5.00, 2.36, 1.92, 3.55) pero SIN
    un total visible, se partía en cuatro apuestas separadas. El usuario
    lo estaba jugando como una sola combinada."""

    def _cupon(self):
        return {"legs": [
            {"match": "Detroit Tigers vs Cleveland Guardians",
             "player": "Max Clark", "group_odds": "5.00"},
            {"match": "Miami Marlins vs Pittsburgh Pirates",
             "player": "Griffin Conine", "group_odds": "2.36"},
            {"match": "Chicago White Sox vs Cincinnati Reds",
             "player": "Davis Martin", "group_odds": "1.92"},
        ]}

    def test_no_se_parte_si_hay_cuota_por_bloque(self):
        from app.analysis.tickets import _dividir_por_partido

        assert len(_dividir_por_partido(self._cupon())) == 1

    def test_conserva_todas_las_selecciones_juntas(self):
        from app.analysis.tickets import _dividir_por_partido

        ticket = _dividir_por_partido(self._cupon())[0]
        assert len(ticket["legs"]) == 3

    def test_sigue_partiendo_cuando_de_verdad_hay_mezcla(self):
        """La red de seguridad tiene que seguir funcionando: sin cuota
        total NI cuota de bloque, varias tarjetas juntas probablemente
        sean un error de lectura."""
        from app.analysis.tickets import _dividir_por_partido

        mezcla = {"legs": [
            {"match": "A vs B", "player": "X"},
            {"match": "C vs D", "player": "Y"},
        ]}
        assert len(_dividir_por_partido(mezcla)) == 2

    def test_la_cuota_total_sigue_mandando(self):
        from app.analysis.tickets import _dividir_por_partido

        con_total = {**self._cupon(), "total_odds": "80.5"}
        assert len(_dividir_por_partido(con_total)) == 1
