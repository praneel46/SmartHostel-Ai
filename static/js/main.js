document.addEventListener("DOMContentLoaded", () => {
  // Ensure GSAP plugins are registered
  if (typeof gsap !== 'undefined') {
    if (typeof ScrollTrigger !== 'undefined') gsap.registerPlugin(ScrollTrigger);
    if (typeof TextPlugin !== 'undefined') gsap.registerPlugin(TextPlugin);
    initAnimations();
    initMagneticCursor();
    initParticleCanvas();
  }

  // Init Matrix if element exists
  if (document.getElementById('hostel-grid') && document.getElementById('pagination-info')) {
    initMatrix();
  }

  // Theme Dropdown Logic
  const themeDropdown = document.getElementById('theme-dropdown') || document.getElementById('theme-dropdown-guest');
  const themeLightBtn = document.getElementById('theme-light') || document.getElementById('theme-light-guest');
  const themeDarkBtn = document.getElementById('theme-dark') || document.getElementById('theme-dark-guest');
  
  if (themeLightBtn && themeDarkBtn) {
    const applyTheme = (theme) => {
      if (theme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
        localStorage.setItem('theme', 'dark');
        if (themeDropdown) themeDropdown.textContent = 'Dark Mode';
      } else {
        document.documentElement.removeAttribute('data-theme');
        localStorage.setItem('theme', 'light');
        if (themeDropdown) themeDropdown.textContent = 'Light Mode';
      }
    };

    // Init display
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    if (themeDropdown) themeDropdown.textContent = currentTheme === 'dark' ? 'Dark Mode' : 'Light Mode';

    themeLightBtn.addEventListener('click', (e) => {
      e.preventDefault();
      applyTheme('light');
    });

    themeDarkBtn.addEventListener('click', (e) => {
      e.preventDefault();
      applyTheme('dark');
    });
  }
});

function initAnimations() {
  // 1. Hero Animations
  const tl = gsap.timeline();

  // Main Headline Typewriter
  if (document.getElementById('hero-headline')) {
    const headline = document.getElementById('hero-headline');
    const textDiv = document.getElementById('hero-headline-text');
    if(headline && textDiv) {
      const fullText = textDiv.innerText.trim();
      const words = fullText.split(/\s+/);
      headline.innerHTML = '<span id="typed-words"></span><span class="typing-cursor"></span>';
      const typedWords = document.getElementById('typed-words');
      gsap.set(headline, { visibility: "visible", opacity: 1 });
      let wordIndex = 0;
      const typeNextWord = () => {
        wordIndex += 1;
        const firstLine = words.slice(0, Math.min(wordIndex, 3)).join(' ');
        const secondLine = wordIndex > 3 ? words.slice(3, wordIndex).join(' ') : '';
        typedWords.innerHTML = secondLine ? `${firstLine}<br>${secondLine}` : firstLine;
        if (wordIndex < words.length) {
          setTimeout(typeNextWord, 230);
        }
      };
      typedWords.innerHTML = '';
      setTimeout(typeNextWord, 180);
      
      tl.to(headline, {
        duration: 0.2,
        opacity: 1,
      });
      
      // Hero Glow Pulse (Cinematic WOW effect)
      gsap.set('.hero-glow', { opacity: 0 });
      tl.to('.hero-glow', {
        opacity: 0.4,
        duration: 0.6,
        ease: "power2.out"
      }, "+=0.1")
      .to('.hero-glow', {
        opacity: 0.15,
        duration: 1.5,
        ease: "power1.inOut"
      });
    }
  }

  // Title Fade-In (Label Second)
  if (document.getElementById('hero-brand')) {
    tl.fromTo("#hero-brand", 
      { y: 15, opacity: 0, scale: 0.95, visibility: "hidden" },
      { y: 0, opacity: 1, scale: 1, visibility: "visible", duration: 0.4, ease: "power2.out" },
      "-=1.5" // Start during the glow pulse
    );
  }

  // Buttons Stagger (Last)
  if (document.getElementById('hero-buttons')) {
    gsap.set("#hero-buttons", { visibility: "visible" });
    tl.fromTo("#hero-buttons .btn", 
      { y: 20, opacity: 0 },
      { y: 0, opacity: 1, duration: 0.5, stagger: 0.15, ease: "power2.out" },
      "-=0.2"
    );
  }

  // Liquid Wave Horizontal Motion (Slow seamless loop)
  const wave = document.querySelector('.liquid-wave');
  if (wave) {
    gsap.to(wave, {
      xPercent: -50,
      ease: "none",
      duration: 20,
      repeat: -1
    });
  }

  const matrixContainer = document.getElementById('matrix-container') || document.getElementById('admin-matrix-container');
  if (matrixContainer) {
    gsap.set(matrixContainer, { opacity: 1, scale: 1 });
  }

  // Navbar Scroll Blur
  const navbar = document.querySelector('.navbar');
  if (navbar) {
    window.addEventListener('scroll', () => {
      if (window.scrollY > 50) {
        navbar.classList.add('navbar-scrolled');
      } else {
        navbar.classList.remove('navbar-scrolled');
      }
    });
  }

  // Features Cards Stagger
  const featureCards = gsap.utils.toArray('.feature-card');
  if (featureCards.length > 0) {
    gsap.fromTo(featureCards,
      { y: 50, opacity: 0 },
      {
        y: 0, opacity: 1,
        duration: 0.8,
        stagger: 0.15,
        ease: "power3.out",
        scrollTrigger: {
          trigger: ".features-section",
          start: "top 75%",
        }
      }
    );
  }

  // Generic Reveal elements
  gsap.utils.toArray('.reveal').forEach(elem => {
    gsap.set(elem, { visibility: "visible" });
    gsap.fromTo(elem,
      { y: 30, opacity: 0 },
      {
        y: 0, opacity: 1,
        duration: 0.8,
        ease: "power3.out",
        scrollTrigger: {
          trigger: elem,
          start: "top 85%"
        }
      }
    );
  });
}

function initMagneticCursor() {
  const cursor = document.getElementById('magnetic-cursor');
  if (!cursor) return;

  // Track mouse and follow smoothly
  gsap.set(cursor, { xPercent: -50, yPercent: -50 });
  
  let xTo = gsap.quickTo(cursor, "x", {duration: 0.4, ease: "power3"}),
      yTo = gsap.quickTo(cursor, "y", {duration: 0.4, ease: "power3"});

  document.addEventListener("mousemove", (e) => {
    // Only show cursor when moving
    gsap.to(cursor, { opacity: 1, duration: 0.3 });
    xTo(e.clientX);
    yTo(e.clientY);
  });

  document.addEventListener("mouseleave", () => {
    gsap.to(cursor, { opacity: 0, duration: 0.3 });
  });
}

function initParticleCanvas() {
  const canvas = document.getElementById('particle-canvas');
  if (!canvas) return;

  // ONLY run on landing page
  if (window.location.pathname !== '/') {
    canvas.style.display = 'none';
    return;
  }

  const ctx = canvas.getContext('2d');
  let width = canvas.width = window.innerWidth;
  let height = canvas.height = window.innerHeight;
  let animationId;
  
  let particles = [];
  const mouse = { x: width / 2, y: height / 2 };
  
  window.addEventListener('resize', () => {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
  });
  
  document.addEventListener('mousemove', (e) => {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
  });
  
  class Particle {
    constructor(layer) {
      this.layer = layer;
      this.reset();
      this.x = width - (Math.random() * width * 0.5); // Start in right half
      this.y = Math.random() * height * 0.5; // Start in top half
    }
    reset() {
      // Spawn from top-right corner area initially
      this.x = width - (Math.random() * width * 0.4);
      this.y = Math.random() * height * 0.4;
      
      const colors = ['#8b5cf6', '#3b82f6', '#22d3ee', '#ffffff'];
      this.color = colors[Math.floor(Math.random() * colors.length)];
      this.targetAlpha = Math.random() * 0.4 + 0.1;
      this.alpha = 0; // Start invisible and fade in

      if (this.layer === 1) { // Background (Far)
        this.vx = 0;
        this.vy = 0;
        this.radius = Math.random() * 1.5 + 0.5;
        this.parallaxMult = 0.01;
        this.repulsion = 0.2; // Slower reaction
        this.driftX = -0.22;
        this.driftY = 0.16;
      } else { // Foreground (Near)
        this.vx = 0;
        this.vy = 0;
        this.radius = Math.random() * 3 + 1.5;
        this.parallaxMult = 0.04;
        this.repulsion = 0.6; // Faster reaction
        this.driftX = -0.48;
        this.driftY = 0.36;
        this.targetAlpha = Math.random() * 0.5 + 0.3;
      }
    }
    update() {
      // Fade in
      if (this.alpha < this.targetAlpha) {
        this.alpha += 0.01;
      }

      // Mouse Repulsion interaction (Antigravity feel)
      const dx = mouse.x - this.x;
      const dy = mouse.y - this.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      
      // Move AWAY from mouse if close
      if (dist < 250) {
        const force = (250 - dist) / 250;
        this.vx -= (dx / dist) * force * this.repulsion;
        this.vy -= (dy / dist) * force * this.repulsion;
      } else {
        // Natural slow drift
        this.vx += (this.driftX - this.vx) * 0.02;
        this.vy += (this.driftY - this.vy) * 0.02;
      }
      
      // Parallax offset based on mouse position relative to center
      const centerX = width / 2;
      const centerY = height / 2;
      const mouseOffsetX = (mouse.x - centerX) * this.parallaxMult;
      const mouseOffsetY = (mouse.y - centerY) * this.parallaxMult;
      
      // Apply physics
      this.vx *= 0.92; // Friction for smooth easing
      this.vy *= 0.92;
      
      this.x += this.vx - mouseOffsetX * 0.05;
      this.y += this.vy - mouseOffsetY * 0.05;
      
      // Smooth reset: Fade out before teleporting
      if (this.x < -100 || this.y > height + 100 || this.x > width + 100 || this.y < -100) {
        this.alpha -= 0.02;
        if (this.alpha <= 0) {
          this.reset();
        }
      }
    }
    draw() {
      ctx.beginPath();
      ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
      
      // Convert hex to rgba to apply alpha
      let hex = this.color.replace('#', '');
      let r = parseInt(hex.substring(0,2), 16);
      let g = parseInt(hex.substring(2,4), 16);
      let b = parseInt(hex.substring(4,6), 16);
      
      ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${this.alpha})`;
      ctx.fill();
    }
  }
  
  // Increase particle count
  for (let i = 0; i < 260; i++) {
    particles.push(new Particle(1)); // background layer
  }
  for (let i = 0; i < 150; i++) {
    particles.push(new Particle(2)); // foreground layer
  }
  
  function animate() {
    ctx.clearRect(0, 0, width, height);
    particles.forEach(p => {
      p.update();
      p.draw();
    });
    animationId = requestAnimationFrame(animate);
  }
  
  animate();

  // Cleanup on leave
  window.addEventListener('beforeunload', () => {
    cancelAnimationFrame(animationId);
  });
}

// Matrix Pagination Logic
let matrixRooms = [];
let currentPage = 1;
const roomsPerPage = 24;

async function initMatrix() {
  const info = document.getElementById('pagination-info');
  const prevBtn = document.getElementById('prev-btn');
  const nextBtn = document.getElementById('next-btn');
  if (!info || !prevBtn || !nextBtn) return;

  try {
    const res = await fetch('/api/rooms');
    const data = await res.json();
    matrixRooms = data.rooms || [];
    renderMatrixPage(1);
  } catch (err) {
    console.error("Failed to fetch matrix rooms:", err);
    info.textContent = "Error loading rooms.";
  }

  prevBtn.addEventListener('click', () => {
    if (currentPage > 1) renderMatrixPage(currentPage - 1);
  });
  
  nextBtn.addEventListener('click', () => {
    const totalPages = Math.ceil(matrixRooms.length / roomsPerPage);
    if (currentPage < totalPages) renderMatrixPage(currentPage + 1);
  });
}

function renderMatrixPage(page) {
  const grid = document.getElementById('hostel-grid');
  const prevBtn = document.getElementById('prev-btn');
  const nextBtn = document.getElementById('next-btn');
  const info = document.getElementById('pagination-info');
  
  const totalPages = Math.ceil(matrixRooms.length / roomsPerPage);
  currentPage = page;

  // Update Buttons
  prevBtn.disabled = currentPage === 1;
  nextBtn.disabled = currentPage === totalPages || totalPages === 0;

  // Calculate slice
  const startIdx = (currentPage - 1) * roomsPerPage;
  const endIdx = Math.min(startIdx + roomsPerPage, matrixRooms.length);
  const currentRooms = matrixRooms.slice(startIdx, endIdx);

  info.textContent = `Showing ${startIdx + 1}-${endIdx} of ${matrixRooms.length} rooms`;

  // Animate Out Old Grid
  if (grid.children.length > 0) {
    if (typeof gsap === 'undefined') {
      populateGrid(currentRooms, grid);
      return;
    }
    gsap.to(grid.children, {
      opacity: 0, x: -20, duration: 0.3, stagger: 0.02,
      onComplete: () => populateGrid(currentRooms, grid)
    });
  } else {
    populateGrid(currentRooms, grid);
  }
}

function populateGrid(rooms, grid) {
  grid.innerHTML = '';
  
  // Create a document fragment to append all rooms at once
  const fragment = document.createDocumentFragment();

  rooms.forEach(room => {
    const statusClass = room.status.toLowerCase();
    const node = document.createElement('div');
    node.className = `room-node ${statusClass}`;
    node.innerHTML = `
      <strong>${room.block}-${room.room_id_display}</strong>
      <small>${room.occupied}/${room.capacity}</small>
    `;
    fragment.appendChild(node);
  });

  grid.appendChild(fragment);

  // Animate the container instead of individual elements for performance
  if (typeof gsap !== 'undefined') {
    gsap.fromTo(grid,
      { opacity: 0, scale: 0.98 },
      { opacity: 1, scale: 1, duration: 0.4, ease: "power2.out" }
    );
  }
}
