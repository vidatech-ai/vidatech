// ─── CONFIG ────────────────────────────────────────
const API = 'https://vidatech-wifi.onrender.com';
let token = localStorage.getItem('vt_token');
let selectedPkg = { id: '', name: 'Hourly', hours: 1, speed: '2 Mbps', price: 10 };
let sessionInterval = null;
let allDevices = [];      // full list for client-side filtering
let activeMacs = new Set(); // MACs that have a paid active session

// ─── PORTAL — PACKAGE SELECTION ─────────────────────
function initPortalPackages() {
  document.querySelectorAll('.pkg-big').forEach(card => {
    card.addEventListener('click', () => {
      document.querySelectorAll('.pkg-big').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      selectedPkg = {
        id: card.dataset.id,
        name: card.querySelector('.pkg-big-name').textContent,
        hours: parseInt(card.dataset.hours),
        speed: card.dataset.speed,
        price: parseInt(card.dataset.price),
