import { Activity, Flag, LayoutDashboard, Link2, LogOut, Menu, Settings, Share2, Shield, Users } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../lib/auth.jsx";

const NAV = [
  { to: "/", label: "My training", icon: LayoutDashboard, end: true },
  { to: "/races", label: "Races", icon: Flag },
  { to: "/connections", label: "Connections", icon: Link2 },
  { to: "/sharing", label: "Sharing", icon: Share2 },
  { to: "/athletes", label: "My athletes", icon: Users },
  { to: "/profile", label: "Profile", icon: Settings },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const nav = user.is_admin ? [...NAV, { to: "/admin", label: "Admin", icon: Shield }] : NAV;

  return (
    <div className="shell">
      <header className="topbar">
        <button className="icon-btn" aria-label="Menu" onClick={() => setOpen(!open)}>
          <Menu size={20} />
        </button>
        <span className="brand">
          <Activity size={18} /> CoachQuest
        </span>
      </header>
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="brand sidebar-brand">
          <Activity size={20} /> CoachQuest
        </div>
        <nav>
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}>
              <Icon size={18} /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="muted small">{user.display_name}</div>
          <button className="link-btn" onClick={logout}>
            <LogOut size={16} /> Sign out
          </button>
        </div>
      </aside>
      {open && <div className="scrim" onClick={() => setOpen(false)} />}
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
