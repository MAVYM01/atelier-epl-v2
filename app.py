# -*- coding: utf-8 -*-
"""
ATELIER MÉCANIQUE EPL - VERSION 1.0
École Polytechnique de Lomé - Juin 2026
Solution professionnelle de gestion d'atelier
"""

import os
import sqlite3
import bcrypt
import re
import qrcode
import io
import csv
import socket
from datetime import datetime, timedelta
from functools import wraps
from io import StringIO

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# ==================== CONFIGURATION ====================
app = Flask(__name__)
app.secret_key = 'epl_lome_2026_secret_key_professionnel'

# Configuration base de données
DATABASE = os.path.join(os.path.dirname(__file__), 'database.db')
# Configuration Flask-Mail (AJOUT)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'victorienattila@gmail.com'  # À remplacer par votre email
app.config['MAIL_PASSWORD'] = 'iksd xptn rigf kwqi'  # À remplacer par votre mot de passe
def get_db():
    """Retourne une connexion à la base SQLite"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Crée toutes les tables et données initiales"""
    db = get_db()
    cur = db.cursor()
    
    # === TABLE UTILISATEURS ===
    cur.execute('''
        CREATE TABLE IF NOT EXISTS utilisateurs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            nom_complet TEXT NOT NULL,
            profession TEXT,
            role TEXT CHECK(role IN ('admin', 'enseignant', 'magasinier', 'etudiant')) NOT NULL,
            password_hash TEXT NOT NULL,
            est_verifie INTEGER DEFAULT 0,
            est_actif INTEGER DEFAULT 1,
            derniere_connexion DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # === TABLE MACHINES ===
    cur.execute('''
        CREATE TABLE IF NOT EXISTS machines (
            id TEXT PRIMARY KEY,
            nom TEXT NOT NULL,
            statut TEXT DEFAULT 'operationnel',
            compteur_heures INTEGER DEFAULT 0,
            disjoncteur TEXT,
            puissance_elec REAL,
            consignes_securite TEXT,
            epi_requis TEXT,
            date_installation DATE,
            derniere_maintenance DATE,
            qr_code_path TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # === TABLE CONSOMMABLES ===
    cur.execute('''
        CREATE TABLE IF NOT EXISTS consommables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE NOT NULL,
            designation TEXT NOT NULL,
            categorie TEXT NOT NULL,
            unite TEXT NOT NULL,
            quantite_stock INTEGER DEFAULT 0,
            stock_minimum INTEGER DEFAULT 10,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # === TABLE SEANCES TP ===
    cur.execute('''
        CREATE TABLE IF NOT EXISTS seances_tp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titre TEXT NOT NULL,
            description TEXT,
            enseignant_id INTEGER,
            date_seance DATE NOT NULL,
            heure_debut TIME,
            heure_fin TIME,
            est_recurrent INTEGER DEFAULT 0,
            recurrence TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (enseignant_id) REFERENCES utilisateurs(id) ON DELETE CASCADE
        )
    ''')
    
    # === TABLE INSCRIPTIONS TP ===
    cur.execute('''
        CREATE TABLE IF NOT EXISTS inscriptions_tp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seance_id INTEGER,
            etudiant_id INTEGER,
            date_inscription DATETIME DEFAULT CURRENT_TIMESTAMP,
            statut TEXT DEFAULT 'inscrit',
            FOREIGN KEY (seance_id) REFERENCES seances_tp(id) ON DELETE CASCADE,
            FOREIGN KEY (etudiant_id) REFERENCES utilisateurs(id) ON DELETE CASCADE
        )
    ''')
    
    # === TABLE RESERVATIONS MACHINE ===
    cur.execute('''
        CREATE TABLE IF NOT EXISTS reservations_machine (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT,
            etudiant_id INTEGER,
            seance_id INTEGER,
            date_reservation DATE,
            heure_debut TIME,
            heure_fin TIME,
            membres_groupe TEXT,
            type_reservation TEXT DEFAULT 'libre',
            ue_projet TEXT,
            commentaire TEXT,
            statut TEXT DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (machine_id) REFERENCES machines(id) ON DELETE CASCADE,
            FOREIGN KEY (etudiant_id) REFERENCES utilisateurs(id) ON DELETE CASCADE,
            FOREIGN KEY (seance_id) REFERENCES seances_tp(id) ON DELETE SET NULL
        )
    ''')

    #connexion
    cur.execute('''
        CREATE TABLE IF NOT EXISTS connexions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utilisateur_id INTEGER,
            date_heure DATETIME DEFAULT CURRENT_TIMESTAMP,
            ip_address TEXT,
            user_agent TEXT,
            FOREIGN KEY (utilisateur_id) REFERENCES utilisateurs(id) ON DELETE CASCADE
        )
    ''')
    
    # === TABLE SUIVIS TP ===
    cur.execute('''
        CREATE TABLE IF NOT EXISTS suivis_tp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reservation_id INTEGER,
            machine_id TEXT,
            date_debut DATETIME,
            date_fin DATETIME,
            statut TEXT DEFAULT 'en_cours',
            commentaire TEXT,
            FOREIGN KEY (reservation_id) REFERENCES reservations_machine(id) ON DELETE CASCADE,
            FOREIGN KEY (machine_id) REFERENCES machines(id) ON DELETE CASCADE
        )
    ''')
    
    # === TABLE TRANSACTIONS ===
    cur.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utilisateur_id INTEGER,
            machine_id TEXT,
            consommable_id INTEGER,
            type_action TEXT,
            quantite INTEGER DEFAULT 0,
            commentaire TEXT,
            date_heure DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (utilisateur_id) REFERENCES utilisateurs(id) ON DELETE CASCADE,
            FOREIGN KEY (machine_id) REFERENCES machines(id) ON DELETE SET NULL,
            FOREIGN KEY (consommable_id) REFERENCES consommables(id) ON DELETE SET NULL
        )
    ''')


    
    # === INSERTION ADMIN PAR DEFAUT ===
    cur.execute("SELECT id FROM utilisateurs WHERE email = 'admin@epl.tg'")
    if not cur.fetchone():
        hashed = bcrypt.hashpw('AdminEPL2026!'.encode('utf-8'), bcrypt.gensalt())
        cur.execute('''
            INSERT INTO utilisateurs (email, username, nom_complet, profession, role, password_hash, est_verifie)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        ''', ('admin@epl.tg', 'admin', 'Administrateur EPL', 'Directeur Technique', 'admin', hashed.decode('utf-8')))
    
    # === INSERTION MACHINES TEST ===
    cur.execute("SELECT id FROM machines LIMIT 1")
    if not cur.fetchone():
        machines_test = [
            ('EPL-TRN-001', 'Tour Parallèle', 'operationnel', 1250, '10A Triphasé', 5.5, 'Ne pas dépasser 1500 tours/min. Vérifier le serrage avant démarrage.', 'Lunettes, Gants, Casque antibruit'),
            ('EPL-FRS-002', 'Fraiseuse Universelle', 'operationnel', 890, '16A Triphasé', 4.0, 'Vérifier le sens de rotation. Évacuer les copeaux proprement.', 'Lunettes, Gants, Blouse'),
            ('EPL-PER-003', 'Perceuse à Colonne', 'panne', 450, '6A Monophasé', 1.5, 'Maintenir fermement la pièce.', 'Lunettes, Masque anti-poussière'),
            ('EPL-SOU-004', 'Poste à Souder MIG', 'reparation', 320, '20A Triphasé', 8.0, 'Zone ventilée. Extincteur à proximité.', 'Masque soudure, Gants cuir, Vêtement ignifugé'),
            ('EPL-PLI-005', 'Presse Plieuse Hydraulique', 'operationnel', 210, '25A Triphasé', 12.0, 'Ne jamais passer les mains sous la presse. Vérifier le parallélisme.', 'Lunettes, Casque, Gants')
        ]
        for m in machines_test:
            cur.execute('''
                INSERT INTO machines (id, nom, statut, compteur_heures, disjoncteur, puissance_elec, consignes_securite, epi_requis)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', m)
    
    # === INSERTION CONSOMMABLES TEST ===
    cur.execute("SELECT id FROM consommables LIMIT 1")
    if not cur.fetchone():
        consommables_test = [
            ('SOU-001', 'Baguettes soudure Ø2.5mm', 'soudure', 'kg', 150, 30),
            ('SOU-002', 'Baguettes soudure Ø3.2mm', 'soudure', 'kg', 35, 40),
            ('COU-001', 'Lames scie ruban', 'coupe', 'unités', 12, 5),
            ('COU-002', 'Forets HSS Ø8mm', 'coupe', 'unités', 18, 10),
            ('COU-003', 'Forets HSS Ø12mm', 'coupe', 'unités', 6, 10),
            ('LUB-001', 'Huile de coupe', 'lubrifiant', 'litres', 25, 20),
            ('LUB-002', 'Graisse industrielle', 'lubrifiant', 'kg', 8, 5),
            ('SEC-001', 'Lunettes protection', 'securite', 'paires', 45, 20),
            ('SEC-002', 'Gants thermiques', 'securite', 'paires', 30, 15)
        ]
        for c in consommables_test:
            cur.execute('''
                INSERT INTO consommables (reference, designation, categorie, unite, quantite_stock, stock_minimum)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', c)
    
    db.commit()
    db.close()
    print("✅ Base de données initialisée avec succès")


from flask_mail import Mail, Message

mail = Mail(app)

def envoyer_email(destinataire, sujet, corps):
    """Envoie un email à un destinataire"""
    try:
        msg = Message(sujet, sender=app.config['MAIL_USERNAME'], recipients=[destinataire])
        msg.body = corps
        mail.send(msg)
        return True
    except Exception as e:
        print(f"❌ Erreur d'envoi d'email: {e}")
        return False
# ==================== LOGIN MANAGER ====================
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Veuillez vous connecter pour accéder à cette page'

class Utilisateur(UserMixin):
    def __init__(self, id, email, username, nom_complet, role, est_verifie, est_actif):
        self.id = id
        self.email = email
        self.username = username
        self.nom_complet = nom_complet
        self.role = role
        self.est_verifie = est_verifie
        self.est_actif = est_actif

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM utilisateurs WHERE id = ?", (user_id,))
    user = cur.fetchone()
    db.close()
    if user:
        return Utilisateur(user['id'], user['email'], user['username'], 
                          user['nom_complet'], user['role'], 
                          user['est_verifie'], user['est_actif'])
    return None

# ==================== DECORATEURS ====================
def roles_requis(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Veuillez vous connecter', 'warning')
                return redirect(url_for('login'))
            if current_user.role not in roles and 'admin' not in roles:
                flash('❌ Accès non autorisé', 'danger')
                return redirect(url_for('dashboard_router'))
            return f(*args, **kwargs)
        return wrapper
    return decorator

def login_required_verifie(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if not current_user.est_verifie:
            flash('⏳ Votre compte est en attente de validation par l\'administrateur', 'warning')
            return redirect(url_for('attente_validation'))
        return f(*args, **kwargs)
    return wrapper

# ==================== ROUTEUR ====================
@app.route('/')
@login_required_verifie
def dashboard_router():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif current_user.role == 'enseignant':
        return redirect(url_for('enseignant_dashboard'))
    elif current_user.role == 'magasinier':
        return redirect(url_for('magasinier_dashboard'))
    else:
        return redirect(url_for('etudiant_dashboard'))

# ==================== AUTHENTIFICATION ====================
@app.route('/inscription', methods=['GET', 'POST'])
def inscription():
    if request.method == 'POST':
        email = request.form['email']
        username = request.form['username']
        nom_complet = request.form['nom_complet']
        profession = request.form.get('profession', '')
        role = request.form['role']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if password != confirm_password:
            flash('❌ Les mots de passe ne correspondent pas', 'danger')
            return redirect(url_for('inscription'))
        
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash('❌ Email invalide', 'danger')
            return redirect(url_for('inscription'))
        
        if len(password) < 6:
            flash('❌ Le mot de passe doit contenir au moins 6 caractères', 'danger')
            return redirect(url_for('inscription'))
        
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        
        db = get_db()
        cur = db.cursor()
        
        cur.execute("SELECT id FROM utilisateurs WHERE email = ?", (email,))
        if cur.fetchone():
            flash('❌ Cet email est déjà utilisé', 'danger')
            db.close()
            return redirect(url_for('inscription'))
        
        cur.execute("SELECT id FROM utilisateurs WHERE username = ?", (username,))
        if cur.fetchone():
            flash('❌ Ce nom d\'utilisateur est déjà pris', 'danger')
            db.close()
            return redirect(url_for('inscription'))
        
        cur.execute("""
            INSERT INTO utilisateurs (email, username, nom_complet, profession, role, password_hash, est_verifie, est_actif)
            VALUES (?, ?, ?, ?, ?, ?, 0, 1)
        """, (email, username, nom_complet, profession, role, hashed.decode('utf-8')))
        db.commit()
        db.close()
        
        flash('✅ Inscription réussie ! Votre compte doit être validé par l\'administrateur', 'success')
        return redirect(url_for('login'))
    
    return render_template('inscription.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard_router'))
    
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT * FROM utilisateurs WHERE email = ?", (email,))
        user = cur.fetchone()
        db.close()
        
        if user:
            if bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
                if not user['est_actif']:
                    flash('❌ Votre compte a été désactivé', 'danger')
                    return redirect(url_for('login'))
                
                utilisateur = Utilisateur(user['id'], user['email'], user['username'], 
                                         user['nom_complet'], user['role'], 
                                         user['est_verifie'], user['est_actif'])
                login_user(utilisateur)
                
                db = get_db()
                cur = db.cursor()
                cur.execute("UPDATE utilisateurs SET derniere_connexion = CURRENT_TIMESTAMP WHERE id = ?", (user['id'],))
                db.commit()
                db.close()
                
                flash(f'✅ Bienvenue {user["nom_complet"]}', 'success')
                return redirect(url_for('dashboard_router'))
        
        flash('❌ Email ou mot de passe incorrect', 'danger')
    
    return render_template('login.html')

@app.route('/attente-validation')
@login_required
def attente_validation():
    return render_template('attente_validation.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    flash('✅ Déconnecté', 'info')
    return redirect(url_for('login'))

# ==================== ADMIN DASHBOARD ====================
@app.route('/admin')
@login_required
@roles_requis('admin')
def admin_dashboard():
    db = get_db()
    cur = db.cursor()
    
    # Statistiques générales
    cur.execute("SELECT COUNT(*) as total FROM machines")
    total_machines = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as total FROM machines WHERE statut = 'panne'")
    machines_panne = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as total FROM machines WHERE statut = 'reparation'")
    machines_reparation = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as total FROM machines WHERE statut = 'operationnel'")
    machines_ok = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as total FROM consommables WHERE quantite_stock <= stock_minimum")
    alertes_stock = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as total FROM utilisateurs WHERE est_verifie = 0")
    inscriptions_attente = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as total FROM utilisateurs WHERE role = 'etudiant' AND est_verifie = 1")
    total_etudiants = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as total FROM utilisateurs WHERE role = 'enseignant' AND est_verifie = 1")
    total_enseignants = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as total FROM utilisateurs WHERE role = 'magasinier' AND est_verifie = 1")
    total_magasiniers = cur.fetchone()['total']
    
    # Inscriptions en attente
    cur.execute("SELECT * FROM utilisateurs WHERE est_verifie = 0 ORDER BY created_at DESC")
    inscriptions = cur.fetchall()
    
    # Machines et consommables
    cur.execute("SELECT * FROM machines ORDER BY nom")
    machines = cur.fetchall()
    
    cur.execute("SELECT * FROM consommables ORDER BY quantite_stock ASC")
    consommables = cur.fetchall()
    
    db.close()
    
    return render_template('admin/dashboard.html',
                         total_machines=total_machines,
                         machines_panne=machines_panne,
                         machines_reparation=machines_reparation,
                         machines_ok=machines_ok,
                         alertes_stock=alertes_stock,
                         inscriptions_attente=inscriptions_attente,
                         total_etudiants=total_etudiants,
                         total_enseignants=total_enseignants,
                         total_magasiniers=total_magasiniers,
                         inscriptions=inscriptions,
                         machines=machines,
                         consommables=consommables)

@app.route('/admin/valider-inscription/<int:user_id>')
@login_required
@roles_requis('admin')
def admin_valider_inscription(user_id):
    db = get_db()
    cur = db.cursor()
    
    # Récupérer l'utilisateur
    cur.execute("SELECT email, nom_complet FROM utilisateurs WHERE id = ?", (user_id,))
    user = cur.fetchone()
    
    if user:
        # Valider l'inscription
        cur.execute("UPDATE utilisateurs SET est_verifie = 1 WHERE id = ?", (user_id,))
        db.commit()
        
        # Envoyer l'email de validation
        sujet = "✅ Votre compte Atelier EPL est validé"
        corps = f"""
            Bonjour {user['nom_complet']},

            Votre compte sur l'application Atelier Mécanique de l'EPL a été validé par l'administrateur.

            Vous pouvez maintenant vous connecter à l'adresse suivante :
            https://mavym.pythonanywhere.com

            Identifiants :
            - Email : {user['email']}
            - Mot de passe : celui que vous avez choisi lors de votre inscription

            Cordialement,
            L'équipe Atelier Mécanique EPL
        """
        envoyer_email(user['email'], sujet, corps)
        flash('✅ Inscription validée et email envoyé', 'success')
    else:
        flash('❌ Utilisateur non trouvé', 'danger')
    
    db.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/refuser-inscription/<int:user_id>')
@login_required
@roles_requis('admin')
def admin_refuser_inscription(user_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM utilisateurs WHERE id = ?", (user_id,))
    db.commit()
    db.close()
    flash('❌ Inscription refusée', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/machine/ajouter', methods=['POST'])
@login_required
@roles_requis('admin')
def admin_ajouter_machine():
    machine_id = request.form['machine_id'].upper().replace(' ', '_')
    nom = request.form['nom']
    disjoncteur = request.form['disjoncteur']
    puissance = float(request.form['puissance'])
    consignes = request.form['consignes']
    epi = request.form['epi']
    
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        INSERT INTO machines (id, nom, disjoncteur, puissance_elec, consignes_securite, epi_requis)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (machine_id, nom, disjoncteur, puissance, consignes, epi))
    db.commit()
    db.close()
    
    flash(f'✅ Machine "{nom}" ajoutée', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/machine/reparer/<machine_id>')
@login_required
@roles_requis('admin')
def admin_reparer_machine(machine_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE machines SET statut = 'operationnel' WHERE id = ?", (machine_id,))
    db.commit()
    
    cur.execute("""
        INSERT INTO transactions (utilisateur_id, machine_id, type_action, commentaire)
        VALUES (?, ?, 'maintenance', 'Machine réparée')
    """, (current_user.id, machine_id))
    db.commit()
    db.close()
    
    flash('✅ Machine déclarée réparée', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/machine/irreparable/<machine_id>')
@login_required
@roles_requis('admin')
def admin_irreparable_machine(machine_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE machines SET statut = 'irreparable' WHERE id = ?", (machine_id,))
    db.commit()
    
    cur.execute("""
        INSERT INTO transactions (utilisateur_id, machine_id, type_action, commentaire)
        VALUES (?, ?, 'maintenance', 'Machine déclarée irréparable')
    """, (current_user.id, machine_id))
    db.commit()
    db.close()
    
    flash('⚠️ Machine déclarée irréparable', 'warning')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/machine/supprimer/<machine_id>')
@login_required
@roles_requis('admin')
def admin_supprimer_machine(machine_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM machines WHERE id = ?", (machine_id,))
    db.commit()
    db.close()
    flash('🗑️ Machine supprimée', 'info')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/consommable/ajouter', methods=['POST'])
@login_required
@roles_requis('admin')
def admin_ajouter_consommable():
    reference = request.form['reference'].upper()
    designation = request.form['designation']
    categorie = request.form['categorie']
    unite = request.form['unite']
    stock_min = int(request.form['stock_minimum'])
    
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        INSERT INTO consommables (reference, designation, categorie, unite, stock_minimum)
        VALUES (?, ?, ?, ?, ?)
    """, (reference, designation, categorie, unite, stock_min))
    db.commit()
    db.close()
    
    flash(f'✅ Consommable "{designation}" ajouté', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/consommable/modifier/<int:cid>', methods=['POST'])
@login_required
@roles_requis('admin')
def admin_modifier_stock(cid):
    quantite = int(request.form['quantite'])
    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE consommables SET quantite_stock = ? WHERE id = ?", (quantite, cid))
    db.commit()
    db.close()
    flash('✅ Stock mis à jour', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/consommable/supprimer/<int:cid>')
@login_required
@roles_requis('admin')
def admin_supprimer_consommable(cid):
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM consommables WHERE id = ?", (cid,))
    db.commit()
    db.close()
    flash('🗑️ Consommable supprimé', 'info')
    return redirect(url_for('admin_dashboard'))

# ==================== ENSEIGNANT DASHBOARD ====================
@app.route('/enseignant')
@login_required
@roles_requis('enseignant')
def enseignant_dashboard():
    db = get_db()
    cur = db.cursor()
    
    # Machines opérationnelles et en panne
    cur.execute("SELECT * FROM machines WHERE statut = 'operationnel' ORDER BY nom")
    machines_ok = cur.fetchall()
    
    cur.execute("SELECT * FROM machines WHERE statut IN ('panne', 'reparation') ORDER BY nom")
    machines_panne = cur.fetchall()
    
    # Alertes stock
    cur.execute("SELECT * FROM consommables WHERE quantite_stock <= stock_minimum")
    alertes = cur.fetchall()
    
    # Mes séances TP
    cur.execute("""
        SELECT s.*, COUNT(i.id) as nb_inscrits
        FROM seances_tp s
        LEFT JOIN inscriptions_tp i ON s.id = i.seance_id
        WHERE s.enseignant_id = ?
        GROUP BY s.id
        ORDER BY s.date_seance DESC
    """, (current_user.id,))
    seances = cur.fetchall()
    
    # TP en cours
    cur.execute("""
        SELECT st.*, u.nom_complet as etudiant_nom, m.nom as machine_nom, s.titre as seance_titre
        FROM suivis_tp st
        JOIN reservations_machine r ON st.reservation_id = r.id
        JOIN inscriptions_tp i ON r.etudiant_id = i.etudiant_id
        JOIN seances_tp s ON i.seance_id = s.id
        JOIN utilisateurs u ON r.etudiant_id = u.id
        JOIN machines m ON st.machine_id = m.id
        WHERE s.enseignant_id = ? AND st.statut = 'en_cours'
        ORDER BY st.date_debut DESC
    """, (current_user.id,))
    tp_en_cours = cur.fetchall()
    
    # NOUVEAU : Récupérer les réservations des étudiants
    cur.execute("""
        SELECT r.*, u.nom_complet as etudiant_nom, m.nom as machine_nom,
               s.titre as seance_titre
        FROM reservations_machine r
        JOIN utilisateurs u ON r.etudiant_id = u.id
        JOIN machines m ON r.machine_id = m.id
        LEFT JOIN seances_tp s ON r.seance_id = s.id
        WHERE r.statut = 'active'
        AND (r.seance_id IN (SELECT id FROM seances_tp WHERE enseignant_id = ?)
             OR r.seance_id IS NULL)
        ORDER BY r.date_reservation ASC
    """, (current_user.id,))
    reservations_etudiants = cur.fetchall()
    
    db.close()
    
    return render_template('enseignant/dashboard.html',
                         machines_ok=machines_ok,
                         machines_panne=machines_panne,
                         alertes=alertes,
                         seances=seances,
                         tp_en_cours=tp_en_cours,
                         reservations_etudiants=reservations_etudiants)  # ← NOUVEAU
@app.route('/enseignant/seance/creer', methods=['GET', 'POST'])
@login_required
@roles_requis('enseignant')
def creer_seance_tp():
    if request.method == 'POST':
        titre = request.form['titre']
        description = request.form['description']
        date_seance = request.form['date_seance']
        heure_debut = request.form['heure_debut']
        heure_fin = request.form['heure_fin']
        est_recurrent = 1 if 'est_recurrent' in request.form else 0
        recurrence = request.form.get('recurrence', '') if est_recurrent else None
        
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            INSERT INTO seances_tp (titre, description, enseignant_id, date_seance, 
                                   heure_debut, heure_fin, est_recurrent, recurrence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (titre, description, current_user.id, date_seance, 
              heure_debut, heure_fin, est_recurrent, recurrence))
        db.commit()
        db.close()
        
        flash('✅ Séance TP créée', 'success')
        return redirect(url_for('enseignant_dashboard'))
    
    return render_template('enseignant/creer_seance.html')

@app.route('/enseignant/seance/<int:seance_id>/inscriptions')
@login_required
@roles_requis('enseignant')
def voir_inscriptions(seance_id):
    db = get_db()
    cur = db.cursor()
    
    cur.execute("""
        SELECT i.*, u.nom_complet, u.email
        FROM inscriptions_tp i
        JOIN utilisateurs u ON i.etudiant_id = u.id
        WHERE i.seance_id = ?
    """, (seance_id,))
    inscriptions = cur.fetchall()
    
    cur.execute("SELECT * FROM seances_tp WHERE id = ?", (seance_id,))
    seance = cur.fetchone()
    
    cur.execute("""
        SELECT st.*, u.nom_complet as etudiant_nom, m.nom as machine_nom
        FROM suivis_tp st
        JOIN reservations_machine r ON st.reservation_id = r.id
        JOIN utilisateurs u ON r.etudiant_id = u.id
        JOIN machines m ON st.machine_id = m.id
        WHERE r.seance_id = ?
        ORDER BY st.date_debut DESC
    """, (seance_id,))
    suivis = cur.fetchall()
    
    db.close()
    
    return render_template('enseignant/inscriptions.html', 
                         inscriptions=inscriptions, seance=seance, suivis=suivis)

@app.route('/enseignant/machine/suspendre/<int:suivi_id>')
@login_required
@roles_requis('enseignant')
def suspendre_utilisation(suivi_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        UPDATE suivis_tp SET statut = 'suspendu', date_fin = CURRENT_TIMESTAMP 
        WHERE id = ?
    """, (suivi_id,))
    db.commit()
    db.close()
    
    flash('⏸️ Utilisation suspendue par l\'enseignant', 'warning')
    return redirect(request.referrer)

# ==================== MAGASINIER DASHBOARD ====================
@app.route('/magasinier')
@login_required
@roles_requis('magasinier')
def magasinier_dashboard():
    db = get_db()
    cur = db.cursor()
    
    cur.execute("SELECT * FROM consommables ORDER BY quantite_stock ASC")
    consommables = cur.fetchall()
    
    cur.execute("""
        SELECT s.*, u.nom_complet as enseignant_nom,
               COUNT(i.id) as nb_etudiants
        FROM seances_tp s
        JOIN utilisateurs u ON s.enseignant_id = u.id
        LEFT JOIN inscriptions_tp i ON s.id = i.seance_id
        WHERE s.date_seance >= DATE('now')
        GROUP BY s.id
        ORDER BY s.date_seance ASC
        LIMIT 15
    """)
    tp_previsionnels = cur.fetchall()
    
    cur.execute("""
        SELECT t.*, c.designation, u.nom_complet
        FROM transactions t
        LEFT JOIN consommables c ON t.consommable_id = c.id
        LEFT JOIN utilisateurs u ON t.utilisateur_id = u.id
        WHERE t.type_action IN ('entree_stock', 'sortie_stock')
        ORDER BY t.date_heure DESC LIMIT 30
    """)
    mouvements = cur.fetchall()
    
    db.close()
    
    return render_template('magasinier/dashboard.html',
                         consommables=consommables,
                         tp_previsionnels=tp_previsionnels,
                         mouvements=mouvements)

@app.route('/magasinier/mouvement', methods=['POST'])
@login_required
@roles_requis('magasinier')
def magasinier_mouvement():
    consommable_id = request.form['consommable_id']
    type_mouvement = request.form['type_mouvement']
    quantite = int(request.form['quantite'])
    commentaire = request.form.get('commentaire', '')
    
    db = get_db()
    cur = db.cursor()
    
    if type_mouvement == 'entree':
        cur.execute("UPDATE consommables SET quantite_stock = quantite_stock + ? WHERE id = ?", 
                   (quantite, consommable_id))
        type_action = 'entree_stock'
    else:
        cur.execute("UPDATE consommables SET quantite_stock = quantite_stock - ? WHERE id = ?", 
                   (quantite, consommable_id))
        type_action = 'sortie_stock'
    
    cur.execute("""
        INSERT INTO transactions (utilisateur_id, consommable_id, type_action, quantite, commentaire)
        VALUES (?, ?, ?, ?, ?)
    """, (current_user.id, consommable_id, type_action, quantite, commentaire))
    
    db.commit()
    db.close()
    
    flash('✅ Mouvement enregistré', 'success')
    return redirect(url_for('magasinier_dashboard'))

# ==================== ETUDIANT DASHBOARD ====================
@app.route('/etudiant')
@login_required
@roles_requis('etudiant')
def etudiant_dashboard():
    db = get_db()
    cur = db.cursor()
    
    # TP disponibles
    cur.execute("""
        SELECT s.*, u.nom_complet as enseignant_nom,
               (SELECT COUNT(*) FROM inscriptions_tp WHERE seance_id = s.id) as nb_inscrits
        FROM seances_tp s
        JOIN utilisateurs u ON s.enseignant_id = u.id
        WHERE s.date_seance >= DATE('now')
        AND s.id NOT IN (SELECT seance_id FROM inscriptions_tp WHERE etudiant_id = ?)
        ORDER BY s.date_seance ASC
    """, (current_user.id,))
    tp_disponibles = cur.fetchall()
    
    # Mes inscriptions
    cur.execute("""
        SELECT s.*, u.nom_complet as enseignant_nom,
               i.date_inscription, i.statut as inscription_statut
        FROM inscriptions_tp i
        JOIN seances_tp s ON i.seance_id = s.id
        JOIN utilisateurs u ON s.enseignant_id = u.id
        WHERE i.etudiant_id = ?
        ORDER BY s.date_seance ASC
    """, (current_user.id,))
    mes_inscriptions = cur.fetchall()
    
    # Machines disponibles
    cur.execute("""
        SELECT m.*, 
               (SELECT COUNT(*) FROM reservations_machine 
                WHERE machine_id = m.id AND statut = 'active' 
                AND date_reservation = DATE('now')) as reservations_auj
        FROM machines m
        WHERE m.statut = 'operationnel'
        ORDER BY m.nom
    """)
    machines = cur.fetchall()
    
    # Mes réservations
    cur.execute("""
        SELECT r.*, m.nom as machine_nom
        FROM reservations_machine r
        JOIN machines m ON r.machine_id = m.id
        WHERE r.etudiant_id = ? AND r.statut = 'active'
        ORDER BY r.date_reservation ASC
    """, (current_user.id,))
    mes_reservations = cur.fetchall()
    
    # Historique
    cur.execute("""
        SELECT t.*, m.nom as machine_nom
        FROM transactions t
        LEFT JOIN machines m ON t.machine_id = m.id
        WHERE t.utilisateur_id = ?
        ORDER BY t.date_heure DESC LIMIT 30
    """, (current_user.id,))
    historique = cur.fetchall()
    
    db.close()
    
    return render_template('etudiant/dashboard.html',
                         tp_disponibles=tp_disponibles,
                         mes_inscriptions=mes_inscriptions,
                         machines=machines,
                         mes_reservations=mes_reservations,
                         historique=historique)

@app.route('/etudiant/inscrire-tp/<int:seance_id>', methods=['POST'])
@login_required
@roles_requis('etudiant')
def inscrire_tp(seance_id):
    db = get_db()
    cur = db.cursor()
    
    cur.execute("SELECT id FROM inscriptions_tp WHERE seance_id = ? AND etudiant_id = ?", 
                (seance_id, current_user.id))
    if cur.fetchone():
        flash('❌ Vous êtes déjà inscrit à cette séance', 'warning')
        db.close()
        return redirect(url_for('etudiant_dashboard'))
    
    cur.execute("""
        INSERT INTO inscriptions_tp (seance_id, etudiant_id, statut)
        VALUES (?, ?, 'inscrit')
    """, (seance_id, current_user.id))
    db.commit()
    db.close()
    
    flash('✅ Inscription au TP confirmée', 'success')
    return redirect(url_for('etudiant_dashboard'))

@app.route('/etudiant/reserver-machine', methods=['POST'])
@login_required
@roles_requis('etudiant')
def reserver_machine():
    machine_id = request.form['machine_id']
    date_reservation = request.form['date_reservation']
    heure_debut = request.form['heure_debut']
    heure_fin = request.form['heure_fin']
    membres_groupe = request.form.get('membres_groupe', '')
    type_reservation = request.form.get('type_reservation', 'LIBRE')
    ue_projet = request.form.get('ue_projet', '')
    commentaire = request.form.get('commentaire', '')
    seance_id = request.form.get('seance_id', None)
    
    db = get_db()
    cur = db.cursor()
    
    # Vérifier les conflits
    cur.execute("""
        SELECT COUNT(*) as count FROM reservations_machine
        WHERE machine_id = ? AND date_reservation = ?
        AND heure_debut < ? AND heure_fin > ?
        AND statut = 'active'
    """, (machine_id, date_reservation, heure_fin, heure_debut))
    
    conflit = cur.fetchone()['count']
    
    if conflit > 0:
        flash('❌ Machine déjà réservée sur ce créneau', 'danger')
    else:
        cur.execute("""
            INSERT INTO reservations_machine 
            (machine_id, etudiant_id, seance_id, date_reservation, 
             heure_debut, heure_fin, membres_groupe, type_reservation, 
             ue_projet, commentaire)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (machine_id, current_user.id, seance_id, date_reservation, 
              heure_debut, heure_fin, membres_groupe, type_reservation, 
              ue_projet, commentaire))
        db.commit()
        flash('✅ Machine réservée avec succès', 'success')
    
    db.close()
    return redirect(url_for('etudiant_dashboard'))

@app.route('/etudiant/debuter-tp/<int:reservation_id>')
@login_required
@roles_requis('etudiant')
def debuter_tp_reservation(reservation_id):
    db = get_db()
    cur = db.cursor()
    
    cur.execute("SELECT * FROM reservations_machine WHERE id = ? AND etudiant_id = ?", 
                (reservation_id, current_user.id))
    reservation = cur.fetchone()
    
    if reservation and reservation['statut'] == 'active':
        cur.execute("""
            INSERT INTO suivis_tp (reservation_id, machine_id, date_debut, statut)
            VALUES (?, ?, CURRENT_TIMESTAMP, 'en_cours')
        """, (reservation_id, reservation['machine_id']))
        
        cur.execute("UPDATE reservations_machine SET statut = 'en_cours' WHERE id = ?", (reservation_id,))
        
        cur.execute("""
            INSERT INTO transactions (utilisateur_id, machine_id, type_action, commentaire)
            VALUES (?, ?, 'debut_tp', 'Début des travaux pratiques')
        """, (current_user.id, reservation['machine_id']))
        
        db.commit()
        flash('🟢 TP démarré', 'success')
    
    db.close()
    return redirect(url_for('etudiant_dashboard'))

@app.route('/etudiant/terminer-tp/<int:suivi_id>')
@login_required
@roles_requis('etudiant')
def terminer_tp(suivi_id):
    db = get_db()
    cur = db.cursor()
    
    cur.execute("SELECT * FROM suivis_tp WHERE id = ?", (suivi_id,))
    suivi = cur.fetchone()
    
    if suivi and suivi['statut'] == 'en_cours':
        cur.execute("UPDATE suivis_tp SET date_fin = CURRENT_TIMESTAMP, statut = 'termine' WHERE id = ?", (suivi_id,))
        cur.execute("UPDATE machines SET compteur_heures = compteur_heures + 2 WHERE id = ?", (suivi['machine_id'],))
        
        cur.execute("""
            INSERT INTO transactions (utilisateur_id, machine_id, type_action, commentaire)
            VALUES (?, ?, 'fin_tp', 'Fin des travaux pratiques')
        """, (current_user.id, suivi['machine_id']))
        
        if suivi['reservation_id']:
            cur.execute("UPDATE reservations_machine SET statut = 'termine' WHERE id = ?", (suivi['reservation_id'],))
        
        db.commit()
        flash('🔴 TP terminé', 'success')
    
    db.close()
    return redirect(url_for('etudiant_dashboard'))

@app.route('/etudiant/annuler-reservation/<int:reservation_id>')
@login_required
@roles_requis('etudiant')
def annuler_reservation(reservation_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE reservations_machine SET statut = 'annule' WHERE id = ? AND etudiant_id = ?", 
                (reservation_id, current_user.id))
    db.commit()
    db.close()
    flash('❌ Réservation annulée', 'info')
    return redirect(url_for('etudiant_dashboard'))

@app.route('/etudiant/action', methods=['POST'])
@login_required
@roles_requis('etudiant', 'enseignant', 'admin')
def etudiant_action():
    machine_id = request.form['machine_id']
    action = request.form['action']
    
    db = get_db()
    cur = db.cursor()
    
    # Vérifier que la machine existe
    cur.execute("SELECT id, nom FROM machines WHERE id = ?", (machine_id,))
    machine = cur.fetchone()
    if not machine:
        flash('❌ Machine non trouvée', 'danger')
        db.close()
        return redirect(url_for('etudiant_dashboard'))
    
    # VÉRIFICATION : Pour "debut_tp", vérifier la date et la réservation
    if action == 'debut_tp':
        # Vérifier si l'étudiant a une réservation active pour cette machine aujourd'hui
        cur.execute("""
            SELECT * FROM reservations_machine 
            WHERE machine_id = ? 
            AND etudiant_id = ? 
            AND date_reservation = DATE('now')
            AND statut = 'active'
        """, (machine_id, current_user.id))
        reservation = cur.fetchone()
        
        if not reservation:
            flash('❌ Vous devez avoir une réservation active pour cette machine aujourd\'hui', 'danger')
            db.close()
            return redirect(url_for('etudiant_dashboard'))
        
        # Vérifier que l'heure actuelle est dans le créneau de réservation
        from datetime import datetime
        now = datetime.now().time()
        heure_debut = datetime.strptime(reservation['heure_debut'], '%H:%M').time()
        heure_fin = datetime.strptime(reservation['heure_fin'], '%H:%M').time()
        
        if now < heure_debut or now > heure_fin:
            flash(f'❌ Vous ne pouvez démarrer qu\'entre {reservation["heure_debut"]} et {reservation["heure_fin"]}', 'danger')
            db.close()
            return redirect(url_for('etudiant_dashboard'))
    
    # Exécuter l'action (début_tp, fin_tp, panne)
    if action == 'debut_tp':
        cur.execute("""
            INSERT INTO transactions (utilisateur_id, machine_id, type_action, commentaire)
            VALUES (?, ?, 'debut_tp', 'Début des travaux pratiques')
        """, (current_user.id, machine_id))
        flash('🟢 TP commencé', 'success')
    
    elif action == 'fin_tp':
        cur.execute("""
            INSERT INTO transactions (utilisateur_id, machine_id, type_action, commentaire)
            VALUES (?, ?, 'fin_tp', 'Fin des travaux pratiques')
        """, (current_user.id, machine_id))
        cur.execute("UPDATE machines SET compteur_heures = compteur_heures + 2 WHERE id = ?", (machine_id,))
        flash('🔴 TP terminé - 2h ajoutées', 'success')
    
    elif action == 'panne':
        cur.execute("""
            INSERT INTO transactions (utilisateur_id, machine_id, type_action, commentaire)
            VALUES (?, ?, 'declaration_panne', 'Panne déclarée')
        """, (current_user.id, machine_id))
        cur.execute("UPDATE machines SET statut = 'panne' WHERE id = ?", (machine_id,))
        flash('⚠️ Panne déclarée', 'warning')
    
    db.commit()
    db.close()
    
    return redirect(url_for('etudiant_dashboard'))

# ==================== DECLARER UNE PANNE ====================
@app.route('/declarer-panne/<machine_id>')
@login_required
def declarer_panne(machine_id):
    """Permet à un enseignant ou un étudiant de déclarer une panne sur une machine"""
    # Vérifier que l'utilisateur a le droit (enseignant, etudiant, admin)
    if current_user.role not in ['enseignant', 'etudiant', 'admin']:
        flash('❌ Accès non autorisé', 'danger')
        return redirect(url_for('dashboard_router'))
    
    db = get_db()
    cur = db.cursor()
    
    # Vérifier que la machine existe
    cur.execute("SELECT id, nom FROM machines WHERE id = ?", (machine_id,))
    machine = cur.fetchone()
    if not machine:
        db.close()
        flash('❌ Machine non trouvée', 'danger')
        return redirect(url_for('dashboard_router'))
    
    # Mettre à jour le statut de la machine
    cur.execute("UPDATE machines SET statut = 'panne' WHERE id = ?", (machine_id,))
    
    # Enregistrer la transaction
    cur.execute("""
        INSERT INTO transactions (utilisateur_id, machine_id, type_action, commentaire)
        VALUES (?, ?, 'declaration_panne', ?)
    """, (current_user.id, machine_id, f"Panne déclarée par {current_user.nom_complet}"))
    
    db.commit()
    db.close()
    
    flash(f'⚠️ Machine "{machine["nom"]}" déclarée en panne', 'warning')
    return redirect(request.referrer or url_for('dashboard_router'))
# ==================== PAGE PUBLIQUE QR CODE ====================
@app.route('/machine/<machine_id>')
def machine_publique(machine_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM machines WHERE id = ?", (machine_id,))
    machine = cur.fetchone()
    
    if not machine:
        return "Machine non trouvée", 404
    
    cur.execute("""
        SELECT t.*, u.nom_complet
        FROM transactions t
        LEFT JOIN utilisateurs u ON t.utilisateur_id = u.id
        WHERE t.machine_id = ?
        ORDER BY t.date_heure DESC LIMIT 10
    """, (machine_id,))
    historique = cur.fetchall()
    
    db.close()
    return render_template('machine_public.html', machine=machine, historique=historique)

# ==================== EXPORTS ====================
@app.route('/export/pdf')
@login_required
def export_pdf():
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
    elements = []
    styles = getSampleStyleSheet()
    
    titre_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], 
                                  fontSize=20, textColor=colors.HexColor('#1a365d'))
    elements.append(Paragraph("Rapport Atelier Mécanique - EPL Lomé", titre_style))
    elements.append(Spacer(1, 0.2*inch))
    elements.append(Paragraph(f"Version 1.0 - Juin 2026", styles['Normal']))
    elements.append(Spacer(1, 0.2*inch))
    elements.append(Paragraph(f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}", styles['Normal']))
    elements.append(Spacer(1, 0.3*inch))
    
    db = get_db()
    cur = db.cursor()
    
    # ============ ADMIN ============
    if current_user.role == 'admin':
        elements.append(Paragraph("📊 Rapport complet - Administration", styles['Heading2']))
        elements.append(Spacer(1, 0.2*inch))
        
        # Machines
        cur.execute("SELECT id, nom, statut, compteur_heures, puissance_elec FROM machines")
        machines = cur.fetchall()
        
        data_machines = [['ID', 'Nom', 'Statut', 'Heures', 'Puissance']]
        statut_fr = {'operationnel': 'Opérationnel', 'panne': 'En panne', 
                     'reparation': 'En réparation', 'irreparable': 'Irréparable'}
        for m in machines:
            data_machines.append([m['id'], m['nom'], statut_fr.get(m['statut'], m['statut']), 
                                  str(m['compteur_heures']), f"{m['puissance_elec']} kW"])
        
        table_machines = Table(data_machines, colWidths=[1.2*inch, 1.5*inch, 1.2*inch, 1*inch, 1*inch])
        table_machines.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a365d')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        elements.append(Paragraph("🛠️ État du parc machine", styles['Heading3']))
        elements.append(Spacer(1, 0.2*inch))
        elements.append(table_machines)
        elements.append(Spacer(1, 0.3*inch))
        
        # Consommables
        cur.execute("SELECT designation, quantite_stock, stock_minimum FROM consommables")
        consommables = cur.fetchall()
        data_consommables = [['Désignation', 'Stock', 'Minimum']]
        for c in consommables:
            data_consommables.append([c['designation'], str(c['quantite_stock']), str(c['stock_minimum'])])
        
        table_consommables = Table(data_consommables, colWidths=[2.5*inch, 1*inch, 1*inch])
        table_consommables.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a365d')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        elements.append(Paragraph("📦 État des stocks", styles['Heading3']))
        elements.append(Spacer(1, 0.2*inch))
        elements.append(table_consommables)
        elements.append(Spacer(1, 0.3*inch))
        
        # Utilisateurs
        cur.execute("SELECT username, nom_complet, role, derniere_connexion FROM utilisateurs")
        users = cur.fetchall()
        data_users = [['Nom', 'Rôle', 'Dernière connexion']]
        for u in users:
            data_users.append([u['nom_complet'], u['role'], u['derniere_connexion'] or 'Jamais'])
        
        table_users = Table(data_users, colWidths=[2*inch, 1.2*inch, 1.5*inch])
        table_users.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a365d')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        elements.append(Paragraph("👥 Utilisateurs", styles['Heading3']))
        elements.append(Spacer(1, 0.2*inch))
        elements.append(table_users)
    
    # ============ ENSEIGNANT ============
    elif current_user.role == 'enseignant':
        elements.append(Paragraph("📊 Rapport - Enseignant", styles['Heading2']))
        elements.append(Spacer(1, 0.2*inch))
        
        # Machines OK
        cur.execute("SELECT id, nom, statut, compteur_heures FROM machines WHERE statut = 'operationnel'")
        machines_ok = cur.fetchall()
        data_ok = [['ID', 'Nom', 'Heures']]
        for m in machines_ok:
            data_ok.append([m['id'], m['nom'], str(m['compteur_heures'])])
        
        table_ok = Table(data_ok, colWidths=[1.2*inch, 1.5*inch, 1*inch])
        table_ok.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#38a169')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        elements.append(Paragraph("✅ Machines opérationnelles", styles['Heading3']))
        elements.append(Spacer(1, 0.2*inch))
        elements.append(table_ok)
        elements.append(Spacer(1, 0.3*inch))
        
        # Machines en panne
        cur.execute("SELECT id, nom, statut FROM machines WHERE statut IN ('panne', 'reparation')")
        machines_panne = cur.fetchall()
        data_panne = [['ID', 'Nom', 'Statut']]
        for m in machines_panne:
            data_panne.append([m['id'], m['nom'], m['statut']])
        
        table_panne = Table(data_panne, colWidths=[1.2*inch, 1.5*inch, 1*inch])
        table_panne.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e53e3e')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        elements.append(Paragraph("🔴 Machines en panne", styles['Heading3']))
        elements.append(Spacer(1, 0.2*inch))
        elements.append(table_panne)
        elements.append(Spacer(1, 0.3*inch))
        
        # Alertes stock
        cur.execute("SELECT designation, quantite_stock, stock_minimum FROM consommables WHERE quantite_stock <= stock_minimum")
        alertes = cur.fetchall()
        if alertes:
            data_alertes = [['Désignation', 'Stock', 'Minimum']]
            for a in alertes:
                data_alertes.append([a['designation'], str(a['quantite_stock']), str(a['stock_minimum'])])
            
            table_alertes = Table(data_alertes, colWidths=[2.5*inch, 1*inch, 1*inch])
            table_alertes.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#ed8936')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('GRID', (0,0), (-1,-1), 1, colors.black),
            ]))
            elements.append(Paragraph("⚠️ Alertes stock", styles['Heading3']))
            elements.append(Spacer(1, 0.2*inch))
            elements.append(table_alertes)
    
    # ============ MAGASINIER ============
    elif current_user.role == 'magasinier':
        elements.append(Paragraph("📊 Rapport - Magasinier", styles['Heading2']))
        elements.append(Spacer(1, 0.2*inch))
        
        # Tous les stocks
        cur.execute("SELECT designation, quantite_stock, stock_minimum FROM consommables ORDER BY quantite_stock ASC")
        stocks = cur.fetchall()
        data_stocks = [['Désignation', 'Stock', 'Minimum']]
        for s in stocks:
            data_stocks.append([s['designation'], str(s['quantite_stock']), str(s['stock_minimum'])])
        
        table_stocks = Table(data_stocks, colWidths=[2.5*inch, 1*inch, 1*inch])
        table_stocks.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a365d')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        elements.append(Paragraph("📦 État des stocks", styles['Heading3']))
        elements.append(Spacer(1, 0.2*inch))
        elements.append(table_stocks)
        elements.append(Spacer(1, 0.3*inch))
        
        # TP prévisionnels
        cur.execute("""
            SELECT s.titre, s.date_seance, u.nom_complet as enseignant_nom
            FROM seances_tp s
            JOIN utilisateurs u ON s.enseignant_id = u.id
            WHERE s.date_seance >= DATE('now')
            ORDER BY s.date_seance ASC
            LIMIT 10
        """)
        tp_previsionnels = cur.fetchall()
        data_tp = [['Titre', 'Date', 'Enseignant']]
        for t in tp_previsionnels:
            data_tp.append([t['titre'], t['date_seance'], t['enseignant_nom']])
        
        table_tp = Table(data_tp, colWidths=[2*inch, 1.2*inch, 1.5*inch])
        table_tp.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a365d')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        elements.append(Paragraph("📅 TP prévisionnels", styles['Heading3']))
        elements.append(Spacer(1, 0.2*inch))
        elements.append(table_tp)
    
    # ============ ÉTUDIANT ============
    else:
        elements.append(Paragraph("📊 Mon historique - Étudiant", styles['Heading2']))
        elements.append(Spacer(1, 0.2*inch))
        
        # Mon historique
        cur.execute("""
            SELECT t.date_heure, m.nom as machine_nom, t.type_action
            FROM transactions t
            LEFT JOIN machines m ON t.machine_id = m.id
            WHERE t.utilisateur_id = ?
            ORDER BY t.date_heure DESC
            LIMIT 30
        """, (current_user.id,))
        historique = cur.fetchall()
        data_hist = [['Date', 'Machine', 'Action']]
        for h in historique:
            data_hist.append([h['date_heure'], h['machine_nom'] or '-', h['type_action']])
        
        table_hist = Table(data_hist, colWidths=[1.5*inch, 1.5*inch, 1.2*inch])
        table_hist.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a365d')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        elements.append(Paragraph("📜 Mes dernières activités", styles['Heading3']))
        elements.append(Spacer(1, 0.2*inch))
        elements.append(table_hist)
    
    db.close()
    doc.build(elements)
    buffer.seek(0)
    
    return send_file(buffer, mimetype='application/pdf', as_attachment=True, 
                     download_name=f"rapport_{datetime.now().strftime('%Y%m%d')}.pdf")
# ==================== API POUR STATISTIQUES ====================
@app.route('/api/stats')
@login_required
def api_stats():
    db = get_db()
    cur = db.cursor()
    
    # Statut des machines
    cur.execute("""
        SELECT statut, COUNT(*) as total
        FROM machines
        GROUP BY statut
    """)
    statuts = cur.fetchall()
    
    # Top machines utilisées
    cur.execute("""
        SELECT m.nom, COUNT(t.id) as utilisations
        FROM machines m
        LEFT JOIN transactions t ON m.id = t.machine_id
        GROUP BY m.id
        ORDER BY utilisations DESC
        LIMIT 5
    """)
    top_machines = cur.fetchall()
    
    db.close()
    
    return jsonify({
        'statuts': [dict(row) for row in statuts],
        'top_machines': [dict(row) for row in top_machines]
    })
# ==================== LANCEMENT ====================
if __name__ == '__main__':
    os.makedirs('qrcodes', exist_ok=True)
    os.makedirs('exports', exist_ok=True)
    os.makedirs('logs', exist_ok=True)
    
    init_db()
    #MAVYM
    print("="*60)
    print(" ATELIER MÉCANIQUE EPL - VERSION 1.0")
    print(" Juin 2026 - École Polytechnique de Lomé")
    print("="*60)
    print(" Base de données SQLite: database.db")
    print("="*60)
    print(" COMPTE ADMIN PAR DÉFAUT MAVYM:")
    print("   Email: admin@epl.tg")
    print("   Mot de passe: AdminEPL2026!")
    print("="*60)
    
    # Détection environnement
    if os.environ.get('PYTHONANYWHERE_DOMAIN'):
        print("🌐 Mode WSGI - Ne pas utiliser app.run()")
    else:
        print("🚀 Mode développement local")
        app.run(host='0.0.0.0', port=5000, debug=True)