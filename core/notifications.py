from core.notification_repository import (
    delete_read_notifications,
    insert_notification,
    mark_notification_read,
    select_notifications,
)


def criar_notificacao(titulo, mensagem, tipo="sistema", perfil_id=1):
    insert_notification(titulo, mensagem, tipo, perfil_id)


def listar_notificacoes(limit=30, perfil_id=1):
    return select_notifications(limit, perfil_id)


def marcar_notificacao_lida(notification_id, perfil_id=1):
    mark_notification_read(notification_id, perfil_id)


def limpar_notificacoes_lidas(perfil_id=1):
    delete_read_notifications(perfil_id)