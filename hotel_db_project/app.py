# app.py — updated with centered windows, improved booking wizard, combobox for type_id,
# delete room/client, auto show available rooms and immediate guest selection.
import psycopg2
from psycopg2 import errors

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime, timedelta, date

WEEKEND_MULTIPLIER = 1.0

def safe_next_id(conn, table, idcol):
    cur = conn.cursor()
    cur.execute(f"SELECT MAX({idcol}) FROM {table}")
    r = cur.fetchone()
    cur.close()
    mx = r[0] if r and r[0] is not None else 0
    return int(mx) + 1

def format_money(x):
    try:
        return f"{float(x):.2f}"
    except:
        return str(x)

def center_window(win, parent=None):
    """Center a window on its parent if mapped, otherwise on screen."""
    win.update_idletasks()
    w = win.winfo_reqwidth()
    h = win.winfo_reqheight()

    x = 0
    y = 0
    try:
        if parent and getattr(parent, "winfo_ismapped", lambda: False)() and parent.winfo_ismapped():
            pw = parent.winfo_width() or parent.winfo_reqwidth()
            ph = parent.winfo_height() or parent.winfo_reqheight()
            px = parent.winfo_rootx() or 0
            py = parent.winfo_rooty() or 0
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
        else:
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            x = (sw - w) // 2
            y = (sh - h) // 2
    except Exception:
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2

    if x < 0: x = 0
    if y < 0: y = 0
    win.geometry(f"{w}x{h}+{x}+{y}")
    try:
        win.deiconify()
    except:
        pass
    try:
        win.lift()
        win.focus_force()
    except:
        pass

# ----------------- Login Dialog -----------------
class LoginDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Авторизация")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.parent = parent

        DEFAULT_DB = {
            "host": "localhost",
            "port": "5432",
            "dbname": "AD_hotel",
            "user": "admin_user",
            "password": "admin123"
        }
        self.vars = {k: tk.StringVar(value=DEFAULT_DB.get(k,"")) for k in DEFAULT_DB}
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        row = 0
        for key in ("host","port","dbname","user","password"):
            ttk.Label(frm, text=key).grid(row=row, column=0, sticky="w", padx=4, pady=4)
            show = "*" if key=="password" else ""
            ttk.Entry(frm, textvariable=self.vars[key], show=show, width=28).grid(row=row, column=1, padx=4, pady=4)
            row += 1

        btn_frame = ttk.Frame(frm)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=(8,0))
        ttk.Button(btn_frame, text="Connect", command=self.on_connect).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="Cancel", command=self.on_cancel).pack(side="left", padx=6)

        self.result = None
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.geometry("460x260")
        self.minsize(420, 240)
        center_window(self, parent)
        self.wait_window()

    def on_connect(self):
        params = {k: v.get().strip() for k,v in self.vars.items()}
        try:
            conn = psycopg2.connect(host=params['host'], port=params['port'],
                                    dbname=params['dbname'], user=params['user'], password=params['password'])
            conn.autocommit = True
            conn.close()
            self.result = params
            self.destroy()
        except Exception as e:
            messagebox.showerror("Ошибка подключения", str(e))

    def on_cancel(self):
        self.result = None
        self.destroy()

# ----------------- Guest View -----------------
class GuestView(tk.Toplevel):
    def __init__(self, parent, conn_params):
        super().__init__(parent)
        self.title("Guest — свободные номера")
        self.geometry("800x500")
        self.transient(parent)
        self.conn_params = conn_params
        self.conn = None
        try:
            self.conn = psycopg2.connect(**conn_params)
            self.conn.autocommit = True
        except Exception as e:
            messagebox.showerror("DB", f"Не удалось подключиться: {e}")
            self.destroy()
            return

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Свободные номера (выберите дату):", font=("Arial", 12, "bold")).pack(side="left")
        self.date_var = tk.StringVar(value=str(date.today()))
        ent = ttk.Entry(top, textvariable=self.date_var, width=12)
        ent.pack(side="left", padx=8)
        ttk.Button(top, text="Показать", command=self.show_available).pack(side="left", padx=8)

        # Tree
        cols = ("room_id","room_number","type","price","capacity","status")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=110, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=(0,10))
        ttk.Label(bottom, text="(Это упрощённый интерфейс для гостя — только просмотр свободных номеров.)").pack(side="left")

        # center & show
        center_window(self, parent)
        self.show_available()

    def show_available(self):
        try:
            dt = datetime.strptime(self.date_var.get(), "%Y-%m-%d").date()
        except:
            messagebox.showerror("Ошибка", "Введена неверная дата, формат YYYY-MM-DD")
            return

        cur = self.conn.cursor()
        q = """
            SELECT r.room_id, r.room_number, rt.name, rt.price, rt.capacity, r.status
            FROM Room r
            JOIN RoomType rt ON r.type_id = rt.type_id
            WHERE r.room_id NOT IN (
                SELECT room_id FROM Booking WHERE start_date <= %s AND end_date > %s
            )
            ORDER BY r.room_id;
        """
        try:
            cur.execute(q, (dt, dt))
            rows = cur.fetchall()
            cur.close()
        except errors.InsufficientPrivilege:
            # у гостя нет доступа к таблице Booking — показываем все номера (без фильтрации по броням)
            cur.close()
            cur = self.conn.cursor()
            cur.execute("""
                SELECT r.room_id, r.room_number, rt.name, rt.price, rt.capacity, r.status
                FROM Room r JOIN RoomType rt ON r.type_id = rt.type_id
                ORDER BY r.room_id;
            """)
            rows = cur.fetchall()
            cur.close()
            messagebox.showwarning("Ограниченные права",
                                   "У вас нет доступа к данным броней — показываются все номера без учёта занятых.")
        except Exception as e:
            cur.close()
            messagebox.showerror("Ошибка БД", str(e))
            return

        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.tree.insert("", "end", values=r)


# ----------------- Main Application (Admin/Manager) -----------------
class MainApp(tk.Tk):
    def __init__(self, conn_params):
        super().__init__()
        self.title("Hotel Admin — UI")
        self.geometry("1200x780")
        self.minsize(1000, 620)
        # center main window on screen
        self.update_idletasks()
        center_window(self, None)

        self.conn_params = conn_params
        self.conn = None
        self.connect_db()
        self.style = ttk.Style(self)
        try:
            self.style.theme_use('clam')
        except:
            pass
        self.style.configure("Sidebar.TButton", font=("Segoe UI", 10), padding=8)
        self.style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"))

        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        sidebar = ttk.Frame(self, width=220, padding=(8,8))
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)

        header = ttk.Label(self, text=f"Connected as: {conn_params['user']}", style="Header.TLabel")
        header.grid(row=0, column=1, sticky="nw", padx=12, pady=8)

        self.content = ttk.Frame(self, padding=10)
        self.content.grid(row=0, column=1, sticky="nsew", padx=12, pady=(48,12))
        self.current_frame = None

        self.nav_buttons = {}
        buttons = [
            ("Справочник","dashboard"),
            ("Номера/Типы","rooms"),
            ("Клиенты","clients"),
            ("Услуги","services"),
            ("Бронирования","bookings"),
            ("Отчёты","reports"),
        ]
        for i,(t,k) in enumerate(buttons):
            b = ttk.Button(sidebar, text=t, style="Sidebar.TButton", command=lambda key=k: self.switch_to(key))
            b.pack(fill="x", pady=6)
            self.nav_buttons[k] = b

        ttk.Separator(sidebar).pack(fill="x", pady=6)
        ttk.Button(sidebar, text="Выйти", command=self.on_exit).pack(fill="x", pady=4)

        self.frames = {}
        self.build_dashboard()
        self.build_rooms_frame()
        self.build_clients_frame()
        self.build_services_frame()
        self.build_bookings_frame()
        self.build_reports_frame()

        self.switch_to("dashboard")

    def connect_db(self):
        try:
            self.conn = psycopg2.connect(**self.conn_params)
            self.conn.autocommit = True
        except Exception as e:
            messagebox.showerror("DB", f"Не удалось подключиться: {e}")
            self.destroy()

    def on_exit(self):
        if messagebox.askyesno("Exit", "Закрыть приложение?"):
            try:
                if self.conn:
                    self.conn.close()
            except:
                pass
            self.destroy()

    def switch_to(self, key):
        if self.current_frame:
            self.current_frame.pack_forget()
        frame = self.frames.get(key)
        if frame:
            frame.pack(fill="both", expand=True)
            self.current_frame = frame

    # ---------- Dashboard ----------
    def build_dashboard(self):
        f = ttk.Frame(self.content)

        # Заголовок
        ttk.Label(f, text="Справочник", style="Header.TLabel").pack(anchor="w", pady=(0, 8))

        # Основной текст — человеческий, на 'Вы'
        text = (
            "Добро пожаловать в административную панель. Ниже краткие инструкции, куда нажать и что можно сделать:\n\n"
            "• Номера/Типы — здесь Вы можете добавлять и удалять типы номеров, "
            "создавать номера, смотреть их статус и цену.\n\n"
            "• Клиенты — добавить нового клиента, удалить клиента, посмотреть предоплаты.\n\n"
            "• Услуги — управлять дополнительными услугами (добавить, удалить, посмотреть список).\n\n"
            "• Бронирования — создать бронь (мастер), удалить бронь, добавить услуги к броням и просмотреть детали.\n\n"
            "• Отчёты — просмотреть свободные номера на выбранную дату и агрегированные расчёты по оплате.\n\n"
            "Если нужно быстро перейти в раздел — используйте кнопки справа (в меню)."
        )

        # Текстовое поле только для чтения (скролл)
        frm_txt = ttk.Frame(f)
        frm_txt.pack(fill="both", expand=True)
        txt = tk.Text(frm_txt, wrap="word", height=16)
        txt.insert("1.0", text)
        txt.configure(state="disabled")  # только чтение
        txt.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=4)

        vsb = ttk.Scrollbar(frm_txt, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=vsb.set)
        vsb.pack(side="left", fill="y")

        # Кнопки-переходы (удобно для новичка)
        btns = ttk.Frame(f)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Label(btns, text="Быстрые переходы:").grid(row=0, column=0, sticky="w", padx=4)

        ttk.Button(btns, text="Перейти в Номера/Типы", command=lambda: self.switch_to("rooms")).grid(row=1, column=0,
                                                                                                     padx=4, pady=6,
                                                                                                     sticky="w")
        ttk.Button(btns, text="Перейти в Клиенты", command=lambda: self.switch_to("clients")).grid(row=1, column=1,
                                                                                                   padx=4, pady=6,
                                                                                                   sticky="w")
        ttk.Button(btns, text="Перейти в Услуги", command=lambda: self.switch_to("services")).grid(row=1, column=2,
                                                                                                   padx=4, pady=6,
                                                                                                   sticky="w")
        ttk.Button(btns, text="Перейти в Бронирования", command=lambda: self.switch_to("bookings")).grid(row=2,
                                                                                                         column=0,
                                                                                                         padx=4, pady=6,
                                                                                                         sticky="w")
        ttk.Button(btns, text="Перейти в Отчёты", command=lambda: self.switch_to("reports")).grid(row=2, column=1,
                                                                                                  padx=4, pady=6,
                                                                                                  sticky="w")

        # Подвеска фрейма
        self.frames["dashboard"] = f

    def refresh_stats(self):
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT COUNT(*) FROM Room")
            rooms = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM Booking WHERE start_date <= current_date AND end_date > current_date")
            occ = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM Client")
            clients = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM Service")
            services = cur.fetchone()[0]
            cur.close()
            messagebox.showinfo("Stats", f"Rooms: {rooms}\nOccupied today: {occ}\nClients: {clients}\nServices: {services}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ---------- Rooms ----------
    def build_rooms_frame(self):
        f = ttk.Frame(self.content)
        ttk.Label(f, text="Номера и Типы", style="Header.TLabel").pack(anchor="w")
        top = ttk.Frame(f); top.pack(fill="x", pady=6)
        ttk.Button(top, text="Refresh", command=self.refresh_rooms).pack(side="left")
        ttk.Button(top, text="Добавить тип", command=self.dialog_add_room_type).pack(side="left", padx=6)
        ttk.Button(top, text="Удалить тип", command=self.dialog_delete_type).pack(side="left", padx=6)
        ttk.Button(top, text="Добавить номер", command=self.dialog_add_room).pack(side="left", padx=6)
        ttk.Button(top, text="Удалить номер", command=self.delete_selected_room).pack(side="left", padx=6)
        cols = ("room_id","room_number","type","status","price","capacity")
        tree = ttk.Treeview(f, columns=cols, show="headings", height=18)
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=110, anchor="center")
        vsb = ttk.Scrollbar(f, orient="vertical", command=tree.yview)
        tree.configure(yscroll=vsb.set)
        tree.pack(side="left", fill="both", expand=True, padx=(0,0))
        vsb.pack(side="left", fill="y")
        self.rooms_tree = tree
        self.frames["rooms"] = f
        self.refresh_rooms()

    def refresh_rooms(self):
        if not self.conn: return
        cur = self.conn.cursor()
        cur.execute("""
            SELECT r.room_id, r.room_number, rt.name, r.status, rt.price, rt.capacity
            FROM Room r JOIN RoomType rt ON r.type_id = rt.type_id
            ORDER BY r.room_id;
        """)
        rows = cur.fetchall()
        cur.close()
        self.rooms_tree.delete(*self.rooms_tree.get_children())
        for r in rows:
            self.rooms_tree.insert("", "end", values=r)

    def dialog_add_room_type(self):
        dlg = ModalAddType(self, self.conn)
        if dlg.result:
            self.refresh_rooms()

    def dialog_delete_type(self):
        # Показываем модалку со списком типов + кнопкой удалить
        cur = self.conn.cursor()
        cur.execute("SELECT type_id, name FROM RoomType ORDER BY type_id")
        types = cur.fetchall()
        cur.close()
        if not types:
            messagebox.showinfo("Нет типов", "Типы номеров не созданы.")
            return
        dlg = tk.Toplevel(self)
        dlg.title("Удалить тип номера")
        dlg.transient(self);
        dlg.grab_set()
        frm = ttk.Frame(dlg, padding=10);
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Выберите тип для удаления:").grid(row=0, column=0, padx=6, pady=6)
        opts = [f"{t[0]} - {t[1]}" for t in types]
        var = tk.StringVar()
        cmb = ttk.Combobox(frm, values=opts, textvariable=var, width=40)
        cmb.grid(row=0, column=1, padx=6, pady=6)

        def on_del():
            sel = var.get().strip()
            if not sel:
                messagebox.showwarning("Выбор", "Выберите тип")
                return
            tid = int(sel.split("-")[0].strip())
            if not messagebox.askyesno("Confirm", f"Удалить тип {tid}? Это удалит все номера этого типа."):
                return
            cur2 = self.conn.cursor()
            try:
                # удаляем сначала связанные брони/комнаты, затем сам тип
                cur2.execute(
                    "DELETE FROM BookingService WHERE booking_id IN (SELECT booking_id FROM Booking WHERE room_id IN (SELECT room_id FROM Room WHERE type_id=%s))",
                    (tid,))
                cur2.execute(
                    "DELETE FROM BookingGuest WHERE booking_id IN (SELECT booking_id FROM Booking WHERE room_id IN (SELECT room_id FROM Room WHERE type_id=%s))",
                    (tid,))
                cur2.execute("DELETE FROM Booking WHERE room_id IN (SELECT room_id FROM Room WHERE type_id=%s)", (tid,))
                cur2.execute("DELETE FROM Room WHERE type_id=%s", (tid,))
                cur2.execute("DELETE FROM RoomType WHERE type_id=%s", (tid,))
                messagebox.showinfo("OK", "Тип удалён")
                dlg.destroy()
                self.refresh_rooms()
                self.refresh_bookings()
                self.refresh_clients()
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
            finally:
                cur2.close()

        ttk.Button(frm, text="Удалить", command=on_del).grid(row=1, column=0, columnspan=2, pady=8)
        center_window(dlg, self)
        dlg.wait_window()

    def dialog_add_room(self):
        dlg = ModalAddRoom(self, self.conn)
        if dlg.result:
            self.refresh_rooms()

    def delete_selected_room(self):
        sel = self.rooms_tree.selection()
        if not sel:
            messagebox.showwarning("Выбор", "Выберите номер")
            return
        rid = self.rooms_tree.item(sel[0])['values'][0]
        user = self.conn_params.get("user","")
        if not user.startswith("admin"):
            messagebox.showwarning("Права", "Удалять может только администратор")
            return
        if not messagebox.askyesno("Confirm", f"Удалить номер {rid}?"):
            return
        cur = self.conn.cursor()
        try:
            cur.execute("DELETE FROM BookingService WHERE booking_id IN (SELECT booking_id FROM Booking WHERE room_id=%s)", (rid,))
            cur.execute("DELETE FROM BookingGuest WHERE booking_id IN (SELECT booking_id FROM Booking WHERE room_id=%s)", (rid,))
            cur.execute("DELETE FROM Booking WHERE room_id=%s", (rid,))
            cur.execute("DELETE FROM Room WHERE room_id=%s", (rid,))
            messagebox.showinfo("OK", "Номер удалён")
            self.refresh_rooms()
            self.refresh_bookings()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
        finally:
            cur.close()

    # ---------- Clients ----------
    def build_clients_frame(self):
        f = ttk.Frame(self.content)
        ttk.Label(f, text="Клиенты", style="Header.TLabel").pack(anchor="w")
        top = ttk.Frame(f); top.pack(fill="x", pady=6)
        ttk.Button(top, text="Refresh", command=self.refresh_clients).pack(side="left")
        ttk.Button(top, text="Добавить клиента", command=self.dialog_add_client).pack(side="left", padx=6)
        ttk.Button(top, text="Удалить клиента", command=self.delete_selected_client).pack(side="left", padx=6)
        cols = ("client_id","full_name","passport","prepayment")
        tree = ttk.Treeview(f, columns=cols, show="headings", height=18)
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=180 if c=="full_name" else 110, anchor="center")
        vsb = ttk.Scrollbar(f, orient="vertical", command=tree.yview)
        tree.configure(yscroll=vsb.set)
        tree.pack(side="left", fill="both", expand=True, padx=(0,0))
        vsb.pack(side="left", fill="y")
        self.clients_tree = tree
        self.frames["clients"] = f
        self.refresh_clients()

    def refresh_clients(self):
        if not self.conn: return
        cur = self.conn.cursor()
        cur.execute("SELECT client_id, full_name, passport_number, prepayment FROM Client ORDER BY client_id")
        rows = cur.fetchall()
        cur.close()
        self.clients_tree.delete(*self.clients_tree.get_children())
        for r in rows:
            self.clients_tree.insert("", "end", values=r)

    def dialog_add_client(self):
        dlg = ModalAddClient(self, self.conn)
        if dlg.result:
            self.refresh_clients()

    def delete_selected_client(self):
        sel = self.clients_tree.selection()
        if not sel:
            messagebox.showwarning("Выбор", "Выберите клиента")
            return
        cid = self.clients_tree.item(sel[0])['values'][0]
        user = self.conn_params.get("user","")
        if not user.startswith("admin"):
            messagebox.showwarning("Права", "Удалять может только администратор")
            return
        if not messagebox.askyesno("Confirm", f"Удалить клиента {cid}?"):
            return
        cur = self.conn.cursor()
        try:
            cur.execute("DELETE FROM BookingGuest WHERE client_id=%s", (cid,))
            cur.execute("DELETE FROM Client WHERE client_id=%s", (cid,))
            messagebox.showinfo("OK", "Клиент удалён")
            self.refresh_clients()
            self.refresh_bookings()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
        finally:
            cur.close()

    # ---------- Services ----------
    def build_services_frame(self):
        f = ttk.Frame(self.content)
        ttk.Label(f, text="Услуги", style="Header.TLabel").pack(anchor="w")
        top = ttk.Frame(f); top.pack(fill="x", pady=6)
        ttk.Button(top, text="Refresh", command=self.refresh_services).pack(side="left")
        ttk.Button(top, text="Добавить услугу", command=self.dialog_add_service).pack(side="left", padx=6)
        ttk.Button(top, text="Удалить услугу", command=self.dialog_delete_service).pack(side="left", padx=6)
        cols = ("service_id","name","price","description")
        tree = ttk.Treeview(f, columns=cols, show="headings", height=18)
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=160 if c=="description" else 120, anchor="center")
        vsb = ttk.Scrollbar(f, orient="vertical", command=tree.yview)
        tree.configure(yscroll=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.services_tree = tree
        self.frames["services"] = f
        self.refresh_services()

    def refresh_services(self):
        if not self.conn: return
        cur = self.conn.cursor()
        cur.execute("SELECT service_id, name, price, description FROM Service ORDER BY service_id")
        rows = cur.fetchall()
        cur.close()
        self.services_tree.delete(*self.services_tree.get_children())
        for r in rows:
            self.services_tree.insert("", "end", values=r)

    def dialog_add_service(self):
        dlg = ModalAddService(self, self.conn)
        if dlg.result:
            self.refresh_services()

    def dialog_delete_service(self):
        sel = self.services_tree.selection()
        if not sel:
            messagebox.showwarning("Выбор", "Выберите услугу")
            return
        sid = self.services_tree.item(sel[0])['values'][0]
        user = self.conn_params.get("user","")
        if not user.startswith("admin"):
            messagebox.showwarning("Права", "Удалять может только администратор")
            return
        if not messagebox.askyesno("Confirm", f"Удалить услугу {sid}?"):
            return
        cur = self.conn.cursor()
        try:
            cur.execute("DELETE FROM BookingService WHERE service_id=%s", (sid,))
            cur.execute("DELETE FROM Service WHERE service_id=%s", (sid,))
            messagebox.showinfo("OK", "Удалено")
            self.refresh_services()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
        finally:
            cur.close()

    # ---------- Bookings ----------
    def build_bookings_frame(self):
        f = ttk.Frame(self.content)
        ttk.Label(f, text="Бронирования", style="Header.TLabel").pack(anchor="w")
        top = ttk.Frame(f); top.pack(fill="x", pady=6)
        ttk.Button(top, text="Refresh", command=self.refresh_bookings).pack(side="left")
        ttk.Button(top, text="Создать бронь (мастер)", command=self.dialog_add_booking).pack(side="left", padx=6)
        ttk.Button(top, text="Удалить бронь", command=self.delete_selected_booking).pack(side="left", padx=6)
        ttk.Button(top, text="Добавить услугу -> бронь", command=self.dialog_add_service_to_booking).pack(side="left", padx=6)

        cols = ("booking_id","room_number","start_date","end_date","booking_fee","guests_count")
        tree = ttk.Treeview(f, columns=cols, show="headings", height=18)
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=120, anchor="center")
        tree.bind("<Double-1>", self.on_booking_double)
        vsb = ttk.Scrollbar(f, orient="vertical", command=tree.yview)
        tree.configure(yscroll=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.bookings_tree = tree
        self.frames["bookings"] = f
        self.refresh_bookings()

    def refresh_bookings(self):
        if not self.conn: return
        cur = self.conn.cursor()
        cur.execute("""
            SELECT b.booking_id, r.room_number, b.start_date, b.end_date, b.booking_fee,
                   (SELECT COUNT(*) FROM BookingGuest bg WHERE bg.booking_id = b.booking_id) as guests_count
            FROM Booking b JOIN Room r ON b.room_id = r.room_id
            ORDER BY b.booking_id;
        """)
        rows = cur.fetchall()
        cur.close()
        self.bookings_tree.delete(*self.bookings_tree.get_children())
        for r in rows:
            self.bookings_tree.insert("", "end", values=r)

    def dialog_add_booking(self):
        dlg = ModalBookingWizard(self, self.conn)
        if dlg.result:
            self.refresh_bookings()
            self.refresh_rooms()
            self.refresh_clients()

    def delete_selected_booking(self):
        sel = self.bookings_tree.selection()
        if not sel:
            messagebox.showwarning("Выбор", "Выберите бронь")
            return
        bid = self.bookings_tree.item(sel[0])['values'][0]
        user = self.conn_params.get("user","")
        if not user.startswith("admin"):
            messagebox.showwarning("Права", "Удалять может только администратор")
            return
        if not messagebox.askyesno("Confirm", f"Удалить бронь {bid}?"):
            return
        cur = self.conn.cursor()
        try:
            cur.execute("DELETE FROM BookingService WHERE booking_id=%s", (bid,))
            cur.execute("DELETE FROM BookingGuest WHERE booking_id=%s", (bid,))
            cur.execute("DELETE FROM Booking WHERE booking_id=%s", (bid,))
            messagebox.showinfo("OK", "Удалено")
            self.refresh_bookings()
            self.refresh_rooms()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
        finally:
            cur.close()

    def dialog_add_service_to_booking(self):
        sel = self.bookings_tree.selection()
        if not sel:
            messagebox.showwarning("Выбор", "Выберите бронь")
            return
        bid = self.bookings_tree.item(sel[0])['values'][0]
        dlg = ModalAddServiceToBooking(self, self.conn, bid)
        if dlg.result:
            self.refresh_bookings()

    def on_booking_double(self, event):
        sel = self.bookings_tree.selection()
        if not sel: return
        bid = self.bookings_tree.item(sel[0])['values'][0]
        dlg = ModalBookingDetails(self, self.conn, bid)

    # ---------- Reports ----------
    def build_reports_frame(self):
        f = ttk.Frame(self.content)
        ttk.Label(f, text="Отчёты", style="Header.TLabel").pack(anchor="w")
        top = ttk.Frame(f); top.pack(fill="x", pady=6)
        ttk.Button(top, text="Свободные номера на дату", command=self.dialog_report_free).pack(side="left", padx=6)
        ttk.Button(top, text="Отчёт по оплатам (агрег.)", command=self.dialog_report_payments).pack(side="left", padx=6)
        self.frames["reports"] = f

    def dialog_report_free(self):
        dlg = ModalReportFree(self, self.conn)

    def dialog_report_payments(self):
        dlg = ModalReportPayments(self, self.conn)

    # ---------- Utilities ----------
    def refresh_all(self):
        self.refresh_rooms(); self.refresh_clients(); self.refresh_services(); self.refresh_bookings()

# ---------------- Modal dialogs (CRUD & wizard) ----------------

class ModalAddType(tk.Toplevel):
    def __init__(self, parent, conn, **kw):
        super().__init__(parent)
        self.title("Добавить тип номера")
        self.transient(parent); self.grab_set()
        self.conn = conn
        frm = ttk.Frame(self, padding=10); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Name").grid(row=0,column=0)
        self.v_name = tk.StringVar(); ttk.Entry(frm, textvariable=self.v_name).grid(row=0,column=1)
        ttk.Label(frm, text="Price").grid(row=1,column=0)
        self.v_price = tk.StringVar(); ttk.Entry(frm, textvariable=self.v_price).grid(row=1,column=1)
        ttk.Label(frm, text="Capacity").grid(row=2,column=0)
        self.v_cap = tk.StringVar(); ttk.Entry(frm, textvariable=self.v_cap).grid(row=2,column=1)
        ttk.Button(frm, text="Add", command=self.on_add).grid(row=3,column=0, columnspan=2, pady=8)
        self.result = False
        center_window(self, parent)
        self.wait_window()

    def on_add(self):
        try:
            name = self.v_name.get().strip()
            price = float(self.v_price.get())
            cap = int(self.v_cap.get())
            tid = safe_next_id(self.conn, "RoomType", "type_id")
            cur = self.conn.cursor()
            cur.execute("INSERT INTO RoomType (type_id, name, price, capacity) VALUES (%s,%s,%s,%s)",
                        (tid, name, price, cap))
            cur.close()
            self.result = True
            self.destroy()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

class ModalAddRoom(tk.Toplevel):
    def __init__(self, parent, conn, **kw):
        super().__init__(parent)
        self.title("Добавить номер")
        self.transient(parent); self.grab_set()
        self.conn = conn
        frm = ttk.Frame(self, padding=10); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Room Number").grid(row=0,column=0)
        self.v_num = tk.StringVar(); ttk.Entry(frm, textvariable=self.v_num).grid(row=0,column=1)

        ttk.Label(frm, text="Type (select)").grid(row=1,column=0)
        self.type_var = tk.StringVar()
        # fetch types
        cur = self.conn.cursor()
        cur.execute("SELECT type_id, name FROM RoomType ORDER BY type_id")
        types = cur.fetchall()
        cur.close()
        opts = [f"{t[0]} - {t[1]}" for t in types]
        cmb = ttk.Combobox(frm, values=opts, textvariable=self.type_var, width=30)
        cmb.grid(row=1, column=1)
        ttk.Button(frm, text="Add", command=self.on_add).grid(row=2,column=0, columnspan=2, pady=8)
        self.result = False
        center_window(self, parent)
        self.wait_window()

    def on_add(self):
        try:
            rnum = self.v_num.get().strip()
            sel = self.type_var.get().strip()
            if not sel:
                messagebox.showerror("Ошибка", "Выберите type")
                return
            tid = int(sel.split("-")[0].strip())
            rid = safe_next_id(self.conn, "Room", "room_id")
            cur = self.conn.cursor()
            cur.execute("INSERT INTO Room (room_id, type_id, room_number, status, week_day_rate) VALUES (%s,%s,%s,%s,%s)",
                        (rid, tid, rnum, 'свободен', 100))
            cur.close()
            self.result = True
            self.destroy()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

class ModalAddClient(tk.Toplevel):
    def __init__(self, parent, conn, **kw):
        super().__init__(parent)
        self.title("Добавить клиента")
        self.transient(parent); self.grab_set()
        self.conn = conn
        frm = ttk.Frame(self, padding=10); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="ФИО").grid(row=0,column=0)
        self.v_name = tk.StringVar(); ttk.Entry(frm, textvariable=self.v_name).grid(row=0,column=1)
        ttk.Label(frm, text="Паспорт").grid(row=1,column=0)
        self.v_pass = tk.StringVar(); ttk.Entry(frm, textvariable=self.v_pass).grid(row=1,column=1)
        ttk.Label(frm, text="Предоплата").grid(row=2,column=0)
        self.v_prep = tk.StringVar(value="0.00"); ttk.Entry(frm, textvariable=self.v_prep).grid(row=2,column=1)
        ttk.Button(frm, text="Add", command=self.on_add).grid(row=3,column=0, columnspan=2, pady=8)
        self.result = False
        center_window(self, parent)
        self.wait_window()

    def on_add(self):
        try:
            name = self.v_name.get().strip()
            passport = self.v_pass.get().strip()
            prepay = float(self.v_prep.get())
            cid = safe_next_id(self.conn, "Client", "client_id")
            cur = self.conn.cursor()
            cur.execute("INSERT INTO Client (client_id, full_name, passport_number, prepayment) VALUES (%s,%s,%s,%s)",
                        (cid, name, passport, prepay))
            cur.close()
            self.result = True
            self.created_id = cid
            self.destroy()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

class ModalAddService(tk.Toplevel):
    def __init__(self, parent, conn, **kw):
        super().__init__(parent)
        self.title("Добавить услугу")
        self.transient(parent); self.grab_set()
        self.conn = conn
        frm = ttk.Frame(self, padding=10); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Name").grid(row=0,column=0)
        self.v_name = tk.StringVar(); ttk.Entry(frm, textvariable=self.v_name).grid(row=0,column=1)
        ttk.Label(frm, text="Price").grid(row=1,column=0)
        self.v_price = tk.StringVar(); ttk.Entry(frm, textvariable=self.v_price).grid(row=1,column=1)
        ttk.Label(frm, text="Desc").grid(row=2,column=0)
        self.v_desc = tk.StringVar(); ttk.Entry(frm, textvariable=self.v_desc).grid(row=2,column=1)
        ttk.Button(frm, text="Add", command=self.on_add).grid(row=3,column=0, columnspan=2, pady=8)
        self.result = False
        center_window(self, parent)
        self.wait_window()

    def on_add(self):
        try:
            name = self.v_name.get().strip()
            price = float(self.v_price.get())
            desc = self.v_desc.get().strip()
            sid = safe_next_id(self.conn, "Service", "service_id")
            cur = self.conn.cursor()
            cur.execute("INSERT INTO Service (service_id, name, price, description) VALUES (%s,%s,%s,%s)",
                        (sid, name, price, desc))
            cur.close()
            self.result = True
            self.destroy()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

class ModalBookingWizard(tk.Toplevel):
    def __init__(self, parent, conn, **kw):
        super().__init__(parent)
        self.title("Мастер создания брони")
        self.transient(parent); self.grab_set()
        self.geometry("900x640")
        self.minsize(760, 520)
        self.conn = conn
        self.parent = parent
        frm = ttk.Frame(self, padding=10); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Кол-во гостей").grid(row=0,column=0)
        self.v_num = tk.IntVar(value=1); ttk.Entry(frm, textvariable=self.v_num, width=6).grid(row=0,column=1)
        ttk.Button(frm, text="Init guests", command=self.init_guests).grid(row=0,column=2, padx=6)
        ttk.Button(frm, text="Clear guests", command=self.clear_guests).grid(row=0,column=3, padx=6)
        self.guest_area = ttk.Frame(frm); self.guest_area.grid(row=1,column=0, columnspan=4, pady=6, sticky="w")
        self.temp_guest_ids = []
        ttk.Label(frm, text="Start YYYY-MM-DD").grid(row=2,column=0)
        self.v_start = tk.StringVar(value=str(date.today())); ttk.Entry(frm, textvariable=self.v_start, width=12).grid(row=2,column=1)
        ttk.Label(frm, text="End YYYY-MM-DD").grid(row=2,column=2)
        self.v_end = tk.StringVar(value=str(date.today()+timedelta(days=1))); ttk.Entry(frm, textvariable=self.v_end, width=12).grid(row=2,column=3)
        # auto refresh available rooms when dates change
        try:
            self.v_start.trace_add('write', lambda *_: self.show_available())
            self.v_end.trace_add('write', lambda *_: self.show_available())
        except AttributeError:
            # fallback for older tkinter
            pass
        ttk.Label(frm, text="Choose room:").grid(row=4,column=0)
        self.v_room = tk.StringVar(); self.cmb_room = ttk.Combobox(frm, textvariable=self.v_room, width=50); self.cmb_room.grid(row=4,column=1,columnspan=3)
        ttk.Button(frm, text="Create booking", command=self.create_booking).grid(row=5,column=0, columnspan=4, pady=8)
        self.result = False
        center_window(self, parent)
        self.init_guests()
        self.show_available()
        self.wait_window()

    def init_guests(self):
        # пересоздаём область гостей и массив фиксированной длины
        for w in self.guest_area.winfo_children():
            w.destroy()

        n = max(1, int(self.v_num.get()))
        self.temp_guest_ids = [None] * n  # фиксированная длина, индекс => слот
        self.guest_comboboxes = []

        ttk.Label(self.guest_area, text=f"Выберите {n} гостей: выберите из списка — гостя закрепит слот").grid(row=0,
                                                                                                               column=0,
                                                                                                               columnspan=4,
                                                                                                               sticky="w")
        clients = self.fetch_clients_for_cmb()

        for i in range(n):
            row = i + 1
            ttk.Label(self.guest_area, text=f"Гость {row}").grid(row=row, column=0, padx=2)
            var = tk.StringVar()
            cmb = ttk.Combobox(self.guest_area, values=clients, textvariable=var, width=50, state="readonly")
            cmb.grid(row=row, column=1, padx=4)

            # запрет прокрутки колесом (чтобы не менять случайно)
            cmb.bind("<MouseWheel>", lambda e: "break")
            cmb.bind("<Button-4>", lambda e: "break")
            cmb.bind("<Button-5>", lambda e: "break")

            # при выборе сразу назначаем в слот по индексу i
            cmb.bind("<<ComboboxSelected>>", lambda e, v=var, c=cmb, idx=i: self.on_guest_selected(v, c, idx))
            self.guest_comboboxes.append(cmb)

        self.lbl_added = ttk.Label(self.guest_area, text=str(self.temp_guest_ids))
        self.lbl_added.grid(row=n + 1, column=0, columnspan=3, sticky="w")

    def on_guest_selected(self, var, cmb_widget, idx):
        sel = var.get().strip()
        if not sel:
            return

        # создание нового гостя
        if sel.startswith("<создать"):
            dlg = ModalAddClient(self, self.conn)
            if not getattr(dlg, "result", False) or not hasattr(dlg, "created_id"):
                # отмена — сбросим выбор
                var.set("")
                return
            new_id = dlg.created_id
            # проверка дубликата среди других слотов
            others = [x for j,x in enumerate(self.temp_guest_ids) if j != idx]
            if new_id in others:
                messagebox.showwarning("Дубликат", "Гость уже добавлен в другом слоте")
                var.set("")
                return
            self.temp_guest_ids[idx] = new_id
            cmb_widget.set(f"{new_id} - (новый гость)")
            cmb_widget.configure(state="disabled")
            self.lbl_added.config(text=str(self.temp_guest_ids))
            return

        # выбор существующего гостя
        try:
            cid = int(sel.split("-")[0].strip())
        except Exception:
            messagebox.showerror("Ошибка", "Не удалось распознать ID гостя")
            var.set("")
            return

        # проверяем дубликат
        others = [x for j,x in enumerate(self.temp_guest_ids) if j != idx]
        if cid in others:
            messagebox.showwarning("Дубликат", "Этот гость уже выбран в другом слоте")
            var.set("")   # сбросить выбор — пользователь может выбрать другого
            return

        # корректно назначаем слот и блокируем combobox
        self.temp_guest_ids[idx] = cid
        cmb_widget.configure(state="disabled")
        self.lbl_added.config(text=str(self.temp_guest_ids))

    def clear_guests(self):
        self.temp_guest_ids = []
        for w in self.guest_area.winfo_children():
            w.destroy()
        self.init_guests()

    def fetch_clients_for_cmb(self):
        cur = self.conn.cursor()
        cur.execute("SELECT client_id, full_name, passport_number FROM Client ORDER BY client_id")
        rows = cur.fetchall(); cur.close()
        lines = [f"{r[0]} - {r[1]} ({r[2]})" for r in rows]
        lines.insert(0,"<создать нового гостя>")
        return lines

    def show_available(self):
        # Пополнение списка доступных комнат и показываем вместимость
        try:
            start = datetime.strptime(self.v_start.get(), "%Y-%m-%d").date()
            end = datetime.strptime(self.v_end.get(), "%Y-%m-%d").date()
            if start >= end:
                self.cmb_room['values'] = []
                self.cmb_room.set("")
                return
        except Exception:
            self.cmb_room['values'] = []
            self.cmb_room.set("")
            return

        cur = self.conn.cursor()
        q = """
            SELECT r.room_id, r.room_number, rt.name, rt.price, rt.capacity
            FROM Room r JOIN RoomType rt ON r.type_id = rt.type_id
            WHERE r.room_id NOT IN (
                SELECT room_id FROM Booking WHERE start_date <= %s AND end_date > %s
            ) ORDER BY r.room_id;
        """
        cur.execute(q, (start, start))
        rows = cur.fetchall()
        cur.close()

        vals = [f"{r[0]} - {r[1]} ({r[2]}) cap={r[4]} price={format_money(r[3])}" for r in rows]
        self.cmb_room['values'] = vals
        if vals:
            self.cmb_room.current(0)
        else:
            self.cmb_room.set("Нет доступных")

    def create_booking(self):
        # Валидация: все слоты заполнены и уникальны
        n_required = len(self.temp_guest_ids)
        if n_required == 0:
            messagebox.showerror("Ошибка", "Укажите количество гостей")
            return

        if any(x is None for x in self.temp_guest_ids):
            messagebox.showerror("Ошибка", "Не все гости выбраны. Заполните все слоты.")
            return

        if len(set(self.temp_guest_ids)) != n_required:
            messagebox.showerror("Ошибка", "Есть дубликаты гостей — исправьте выбор.")
            return

        sel = self.v_room.get().strip()
        if not sel or sel.startswith("Нет") or sel == "":
            messagebox.showerror("Ошибка", "Выберите комнату")
            return

        try:
            room_id = int(sel.split("-")[0].strip())
            start = datetime.strptime(self.v_start.get(), "%Y-%m-%d").date()
            end = datetime.strptime(self.v_end.get(), "%Y-%m-%d").date()
            if start >= end:
                messagebox.showerror("Ошибка", "Start должен быть раньше End")
                return
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
            return

        cur = self.conn.cursor()
        try:
            bid = safe_next_id(self.conn, "Booking", "booking_id")
            cur.execute("INSERT INTO Booking (booking_id, room_id, start_date, end_date, booking_fee) VALUES (%s,%s,%s,%s,%s)",
                        (bid, room_id, start, end, None))
            for cid in self.temp_guest_ids:
                cbid = safe_next_id(self.conn, "BookingGuest", "client_b_id")
                cur.execute("INSERT INTO BookingGuest (client_b_id, booking_id, client_id) VALUES (%s,%s,%s)",
                            (cbid, bid, cid))
            messagebox.showinfo("OK", f"Бронь создана id={bid}")
            self.result = True
            self.destroy()
        except Exception as e:
            messagebox.showerror("Ошибка БД при создании брони", str(e))
        finally:
            cur.close()

class ModalAddServiceToBooking(tk.Toplevel):
    def __init__(self, parent, conn, booking_id, **kw):
        super().__init__(parent)
        self.title(f"Добавить услугу в бронь {booking_id}")
        self.transient(parent); self.grab_set()
        self.conn = conn; self.bid = booking_id
        frm = ttk.Frame(self, padding=10); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Service").grid(row=0,column=0)
        cur = conn.cursor(); cur.execute("SELECT service_id, name, price FROM Service ORDER BY service_id"); services = cur.fetchall(); cur.close()
        self.services = services
        if not services:
            messagebox.showinfo("Нет услуг", "Добавь услуги на вкладке Services")
            self.result = False; self.destroy(); return
        opts = [f"{s[0]} - {s[1]} ({format_money(s[2])})" for s in services]
        self.var = tk.StringVar()
        ttk.Combobox(frm, values=opts, textvariable=self.var, width=50).grid(row=0,column=1)
        ttk.Label(frm, text="Quantity").grid(row=1,column=0)
        self.qty = tk.IntVar(value=1); ttk.Entry(frm, textvariable=self.qty, width=6).grid(row=1,column=1, sticky="w")
        ttk.Button(frm, text="Add", command=self.on_add).grid(row=2,column=0, columnspan=2, pady=8)
        self.result = False
        center_window(self, parent)
        self.wait_window()

    def on_add(self):
        sel = self.var.get().strip()
        if not sel:
            messagebox.showwarning("Выбор", "Выберите услугу"); return
        sid = int(sel.split("-")[0].strip())
        q = max(1, int(self.qty.get()))
        cur = self.conn.cursor()
        try:
            for _ in range(q):
                sbid = safe_next_id(self.conn, "BookingService", "service_b_id")
                cur.execute("INSERT INTO BookingService (service_b_id, booking_id, service_id) VALUES (%s,%s,%s)", (sbid, self.bid, sid))
            messagebox.showinfo("OK", "Добавлено")
            self.result = True
            self.destroy()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
        finally:
            cur.close()

class ModalBookingDetails(tk.Toplevel):
    def __init__(self, parent, conn, booking_id, **kw):
        super().__init__(parent)
        self.title(f"Details for Booking {booking_id}")
        self.transient(parent); self.grab_set()
        self.conn = conn; self.bid = booking_id
        frm = ttk.Frame(self, padding=10); frm.pack(fill="both", expand=True)
        cur = conn.cursor()
        cur.execute("""
            SELECT b.booking_id, r.room_number, b.start_date, b.end_date, b.booking_fee, rt.price
            FROM Booking b JOIN Room r ON b.room_id=r.room_id JOIN RoomType rt ON r.type_id=rt.type_id
            WHERE b.booking_id=%s
        """, (booking_id,))
        head = cur.fetchone()
        cur.execute("""SELECT c.client_id, c.full_name, c.passport_number, c.prepayment FROM BookingGuest bg JOIN Client c ON bg.client_id=c.client_id WHERE bg.booking_id=%s ORDER BY c.client_id""", (booking_id,))
        guests = cur.fetchall()
        cur.execute("""
            SELECT s.service_id, s.name, s.price, COUNT(bs.service_b_id) as qty
            FROM BookingService bs JOIN Service s ON bs.service_id = s.service_id
            WHERE bs.booking_id=%s
            GROUP BY s.service_id, s.name, s.price
            ORDER BY s.service_id
        """, (booking_id,))
        services = cur.fetchall()
        cur.close()
        if not head:
            messagebox.showerror("Not found", "Booking not found"); self.destroy(); return
        bid, room_num, sdate, edate, bfee, price = head
        nights = (edate - sdate).days
        room_total = nights * float(price)
        services_total = sum([float(s[2]) * int(s[3]) for s in services]) if services else 0.0
        total = room_total + float(bfee or 0.0) + services_total
        prepayments = sum([float(g[3] or 0.0) for g in guests]) if guests else 0.0
        diff = round(prepayments - total, 2)
        if abs(diff) <= 1.0:
            note = "OK"
        elif diff > 1.0:
            note = f"Переплата ({format_money(diff)})"
        else:
            note = f"Недооплата ({format_money(-diff)})"
        ttk.Label(frm, text=f"Booking {bid} — Room {room_num} — {sdate} → {edate}", font=("Arial",12,"bold")).pack(anchor="w")
        ttk.Label(frm, text=f"Nights: {nights}  Room total: {format_money(room_total)}  Services: {format_money(services_total)}  Booking fee: {format_money(bfee)}  TOTAL: {format_money(total)}").pack(anchor="w")
        ttk.Label(frm, text=f"Prepayments sum: {format_money(prepayments)} => {note}").pack(anchor="w", pady=(0,6))
        ttk.Label(frm, text="Guests:").pack(anchor="w")
        tg = ttk.Treeview(frm, columns=("id","name","passport","prepayment"), show="headings", height=6)
        for c in ("id","name","passport","prepayment"):
            tg.heading(c, text=c); tg.column(c, width=140, anchor="center")
        tg.pack(fill="x", padx=4, pady=4)
        for g in guests: tg.insert("", "end", values=g)
        ttk.Label(frm, text="Services:").pack(anchor="w")
        ts = ttk.Treeview(frm, columns=("sid","name","price","qty","sum"), show="headings", height=6)
        for h in ("sid","name","price","qty","sum"):
            ts.heading(h, text=h); ts.column(h, width=120, anchor="center")
        ts.pack(fill="x", padx=4, pady=4)
        for s in services:
            sid, name, price_s, qty = s
            ts.insert("", "end", values=(sid,name,format_money(price_s),qty,format_money(float(price_s)*int(qty))))
        ttk.Button(frm, text="Close", command=self.destroy).pack(pady=8)
        center_window(self, parent)

class ModalReportFree(tk.Toplevel):
    def __init__(self, parent, conn, **kw):
        super().__init__(parent)
        self.title("Отчёт: свободные номера")
        self.transient(parent); self.grab_set()
        self.conn = conn
        frm = ttk.Frame(self, padding=10); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Date YYYY-MM-DD").grid(row=0,column=0)
        self.v_date = tk.StringVar(value=str(date.today()))
        ttk.Entry(frm, textvariable=self.v_date).grid(row=0,column=1)
        ttk.Button(frm, text="Show", command=self.show).grid(row=0,column=2, padx=6)
        cols = ("room_id","room_number","type","price")
        self.tree = ttk.Treeview(frm, columns=cols, show="headings", height=16)
        for c in cols:
            self.tree.heading(c, text=c); self.tree.column(c, width=140, anchor="center")
        self.tree.grid(row=1, column=0, columnspan=3, pady=8, sticky="nsew")
        frm.rowconfigure(1, weight=1)
        center_window(self, parent)
        self.show()

    def show(self):
        try:
            dt = datetime.strptime(self.v_date.get(), "%Y-%m-%d").date()
        except:
            messagebox.showerror("Ошибка", "Неверная дата"); return
        cur = self.conn.cursor()
        cur.execute("""
            SELECT r.room_id, r.room_number, rt.name, rt.price
            FROM Room r JOIN RoomType rt ON r.type_id = rt.type_id
            WHERE r.room_id NOT IN (SELECT room_id FROM Booking WHERE start_date <= %s AND end_date > %s)
            ORDER BY r.room_id
        """, (dt,dt))
        rows = cur.fetchall(); cur.close()
        self.tree.delete(*self.tree.get_children())
        for r in rows: self.tree.insert("", "end", values=r)

class ModalReportPayments(tk.Toplevel):
    def __init__(self, parent, conn, **kw):
        super().__init__(parent)
        self.title("Отчёт: расчёты по оплате (агрег.)")
        self.transient(parent); self.grab_set()
        self.conn = conn
        frm = ttk.Frame(self, padding=10); frm.pack(fill="both", expand=True)
        self.txt = tk.Text(frm, width=120, height=30)
        self.txt.pack(fill="both", expand=True)
        center_window(self, parent)
        self.fill()

    def fill(self):
        cur = self.conn.cursor()
        cur.execute("SELECT b.booking_id FROM Booking b ORDER BY b.booking_id")
        bids = [r[0] for r in cur.fetchall()]
        lines = []
        for bid in bids:
            cur.execute("SELECT nights, room_total, services_total, booking_fee, prepayments_total, balance FROM calc_booking_totals(%s)", (bid,))
            res = cur.fetchone()
            if not res: continue
            nights, room_total, services_total, booking_fee, prepayments_total, balance = res
            total = room_total + (booking_fee or 0) + (services_total or 0)
            note = "OK" if abs(balance) <= 1.0 else ("Переплата" if balance>1.0 else "Недооплата")
            lines.append(f"Booking {bid}: nights={nights} room={format_money(room_total)} services={format_money(services_total)} fee={format_money(booking_fee)} total={format_money(total)} prepayments={format_money(prepayments_total)} => {note}")
            cur.execute("""SELECT c.client_id, c.full_name, c.prepayment FROM BookingGuest bg JOIN Client c ON bg.client_id=c.client_id WHERE bg.booking_id=%s ORDER BY c.client_id""",(bid,))
            guests = cur.fetchall()
            for g in guests:
                lines.append(f"  {g[0]} | {g[1]} | prepay={format_money(g[2])}")
            cur.execute("""
                SELECT s.service_id, s.name, s.price, COUNT(bs.service_b_id) as qty
                FROM BookingService bs JOIN Service s ON bs.service_id=s.service_id
                WHERE bs.booking_id=%s GROUP BY s.service_id, s.name, s.price
            """,(bid,))
            servs = cur.fetchall()
            if servs:
                lines.append("  Services:")
                for s in servs:
                    lines.append(f"    {s[0]} | {s[1]} | price={format_money(s[2])} | qty={s[3]} | sum={format_money(float(s[2])*int(s[3]))}")
            lines.append("-"*100)
        cur.close()
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", "\n".join(lines))

# ----------------- App entry -----------------
def is_guest_user(user):
    user = (user or "").lower()
    return user.startswith("guest") or user == "guest_user"

def main():
    root = tk.Tk()
    root.update_idletasks()
    center_window(root, None)
    login = LoginDialog(root)
    if not login.result:
        try: root.destroy()
        except: pass
        return
    params = login.result
    try: root.destroy()
    except: pass
    if is_guest_user(params.get("user","")):
        guest_root = tk.Tk()
        guest_root.withdraw()
        gv = GuestView(guest_root, params)
        guest_root.mainloop()
    else:
        app = MainApp(params)
        app.mainloop()

if __name__ == "__main__":
    main()
