# -*- coding: utf-8 -*-
"""
motor_busca.py
Ponto de entrada histórico, mantido para o Agendador de Tarefas e o
acordar_e_processar.ps1 continuarem funcionando sem mudar nada. A lógica
real (coleta diária compartilhada por rota + avisos sem preço-alvo) está
em coleta_diaria.py.

Uso:  python motor_busca.py
"""
from coleta_diaria import configurar_logs, executar

if __name__ == "__main__":
    configurar_logs()
    executar()
