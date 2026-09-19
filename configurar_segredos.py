import tkinter as tk
from tkinter import messagebox

from cryptography.fernet import Fernet

from core.app_secrets import carregar_segredos, salvar_segredos


def main():
    root = tk.Tk()
    root.title("Configuração segura - Growth Engine")
    root.resizable(False, False)

    fields = {}
    labels = (
        ("GOOGLE_CLIENT_ID", False),
        ("GOOGLE_CLIENT_SECRET", True),
        ("GOOGLE_TOKEN_ENCRYPTION_KEY (opcional)", True),
    )
    for row, (label, masked) in enumerate(labels):
        tk.Label(root, text=label).grid(row=row, column=0, padx=12, pady=(12 if row == 0 else 6), sticky="w")
        entry = tk.Entry(root, width=58, show="*" if masked else "")
        entry.grid(row=row, column=1, padx=(0, 12), pady=(12 if row == 0 else 6))
        fields[label] = entry

    def save():
        client_id = fields["GOOGLE_CLIENT_ID"].get().strip()
        client_secret = fields["GOOGLE_CLIENT_SECRET"].get().strip()
        token_key = fields["GOOGLE_TOKEN_ENCRYPTION_KEY (opcional)"].get().strip()
        if not client_id or not client_secret:
            messagebox.showerror("Dados incompletos", "Preencha o Client ID e o Client Secret reais.")
            return
        if not token_key:
            token_key = carregar_segredos().get("GOOGLE_TOKEN_ENCRYPTION_KEY")
        try:
            Fernet(token_key.encode("utf-8"))
        except (ValueError, TypeError):
            token_key = Fernet.generate_key().decode("ascii")
        salvar_segredos({
            "GOOGLE_CLIENT_ID": client_id,
            "GOOGLE_CLIENT_SECRET": client_secret,
            "GOOGLE_TOKEN_ENCRYPTION_KEY": token_key,
        })
        messagebox.showinfo("Concluído", "Credenciais protegidas com sucesso.")
        root.destroy()

    tk.Button(root, text="Salvar credenciais", command=save).grid(row=len(labels), column=0, columnspan=2, pady=16)
    root.mainloop()


def main_terminal():
    print("Configuração segura do Growth Engine")
    print("Cole com o botão direito do mouse; a entrada ficará oculta.\n")
    client_id = input("GOOGLE_CLIENT_ID: ").strip()
    client_secret = input("GOOGLE_CLIENT_SECRET: ").strip()
    token_key = input("GOOGLE_TOKEN_ENCRYPTION_KEY (Enter para preservar a atual/gerar): ").strip()
    if not token_key:
        token_key = carregar_segredos().get("GOOGLE_TOKEN_ENCRYPTION_KEY")
    try:
        Fernet(token_key.encode("utf-8"))
    except (ValueError, TypeError):
        token_key = Fernet.generate_key().decode("ascii")
    salvar_segredos({
        "GOOGLE_CLIENT_ID": client_id,
        "GOOGLE_CLIENT_SECRET": client_secret,
        "GOOGLE_TOKEN_ENCRYPTION_KEY": token_key,
    })
    print("Configuração salva em config.secrets.")


if __name__ == "__main__":
    main()