/* =====================================================================
   ZOMBIE SURVIVORS  —  自走射擊 / 倖存者類玩法
   純 JavaScript + Canvas，無外部相依，手機/電腦皆可玩。
   設計重點放在玩法與行為邏輯：敵人 AI、波次節奏、武器系統、升級。
   ===================================================================== */
(() => {
  "use strict";

  // ---------- Canvas setup ----------
  const canvas = document.getElementById("game");
  const ctx = canvas.getContext("2d");
  let W = 0, H = 0, DPR = 1;

  function resize() {
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width = Math.floor(W * DPR);
    canvas.height = Math.floor(H * DPR);
    canvas.style.width = W + "px";
    canvas.style.height = H + "px";
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }
  window.addEventListener("resize", resize);
  resize();

  // ---------- Helpers ----------
  const rand = (a, b) => a + Math.random() * (b - a);
  const randInt = (a, b) => Math.floor(rand(a, b + 1));
  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
  const dist2 = (ax, ay, bx, by) => {
    const dx = ax - bx, dy = ay - by;
    return dx * dx + dy * dy;
  };
  const TAU = Math.PI * 2;

  // ---------- Game state ----------
  const GameState = { MENU: 0, PLAYING: 1, LEVELUP: 2, OVER: 3, PAUSED: 4 };
  let state = GameState.MENU;

  const world = {
    time: 0,        // survival time (s)
    kills: 0,
    // camera follows player; world coords are centered on player
  };

  let player, zombies, projectiles, gems, particles, pickups, damageTexts;

  // ---------- Input ----------
  const keys = {};
  window.addEventListener("keydown", (e) => {
    keys[e.key.toLowerCase()] = true;
    if (e.key === "Escape") togglePause();
    if ([" ", "arrowup", "arrowdown", "arrowleft", "arrowright"].includes(e.key.toLowerCase())) e.preventDefault();
  });
  window.addEventListener("keyup", (e) => { keys[e.key.toLowerCase()] = false; });

  // Virtual joystick (touch)
  const joy = { active: false, baseX: 0, baseY: 0, dx: 0, dy: 0, id: null };
  const joyEl = document.getElementById("joystick");
  const joyKnob = document.getElementById("joystick-knob");
  const JOY_R = 46;
  const isTouch = ("ontouchstart" in window) || navigator.maxTouchPoints > 0;

  function joyStart(x, y, id) {
    joy.active = true; joy.id = id;
    joy.baseX = x; joy.baseY = y;
    joyEl.style.left = (x - 60) + "px";
    joyEl.style.top = (y - 60) + "px";
    joyEl.style.bottom = "auto";
    joyEl.classList.remove("hidden");
    joyMove(x, y);
  }
  function joyMove(x, y) {
    let dx = x - joy.baseX, dy = y - joy.baseY;
    const len = Math.hypot(dx, dy) || 1;
    const cl = Math.min(len, JOY_R);
    dx = (dx / len); dy = (dy / len);
    joy.dx = dx * (cl / JOY_R);
    joy.dy = dy * (cl / JOY_R);
    joyKnob.style.transform = `translate(${dx * cl}px, ${dy * cl}px)`;
  }
  function joyEnd() {
    joy.active = false; joy.id = null; joy.dx = 0; joy.dy = 0;
    joyKnob.style.transform = "translate(0,0)";
  }

  canvas.addEventListener("touchstart", (e) => {
    if (state !== GameState.PLAYING) return;
    for (const t of e.changedTouches) {
      if (!joy.active) { joyStart(t.clientX, t.clientY, t.identifier); }
    }
    e.preventDefault();
  }, { passive: false });
  canvas.addEventListener("touchmove", (e) => {
    for (const t of e.changedTouches) {
      if (t.identifier === joy.id) joyMove(t.clientX, t.clientY);
    }
    e.preventDefault();
  }, { passive: false });
  const endTouch = (e) => {
    for (const t of e.changedTouches) {
      if (t.identifier === joy.id) joyEnd();
    }
  };
  canvas.addEventListener("touchend", endTouch);
  canvas.addEventListener("touchcancel", endTouch);

  // ---------- Player ----------
  function makePlayer() {
    return {
      x: 0, y: 0,
      r: 16,
      speed: 175,
      maxHp: 100, hp: 100,
      regen: 0,            // hp per second
      level: 1, xp: 0, xpNext: 5,
      magnet: 90,          // gem pickup radius
      facing: 1,           // -1 left / 1 right
      iframe: 0,           // invulnerability after hit
      moveX: 0, moveY: 0,
      pickupRange: 90,
      weapons: [],
      stats: { dmgMul: 1, fireRateMul: 1, projSpeedMul: 1, areaMul: 1, projAdd: 0, critChance: 0.05 },
    };
  }

  // ---------- Weapons ----------
  // Each weapon: type, level, cooldown timer. Fire logic in fireWeapon().
  const WEAPON_DEFS = {
    pistol:  { name: "手槍", icon: "🔫", base: { cd: 0.55, dmg: 12, speed: 480, count: 1, pierce: 1 } },
    shotgun: { name: "霰彈槍", icon: "💥", base: { cd: 1.1, dmg: 9, speed: 430, count: 5, spread: 0.55, pierce: 1, range: 320 } },
    orbit:   { name: "迴旋利刃", icon: "🌀", base: { cd: 0, dmg: 10, count: 2, radius: 70, rotSpeed: 2.6, tickRate: 0.25 } },
    aura:    { name: "毒氣領域", icon: "☠️", base: { cd: 0, dmg: 7, radius: 95, tickRate: 0.4 } },
    laser:   { name: "雷射", icon: "⚡", base: { cd: 1.6, dmg: 26, speed: 900, count: 1, pierce: 99 } },
  };

  function addWeapon(type) {
    const def = WEAPON_DEFS[type];
    const w = { type, level: 1, timer: 0, tick: 0, angle: 0, blades: [] };
    player.weapons.push(w);
    return w;
  }
  function hasWeapon(type) { return player.weapons.some((w) => w.type === type); }
  function getWeapon(type) { return player.weapons.find((w) => w.type === type); }

  // Returns scaled stats for a weapon based on its level.
  function weaponStats(w) {
    const b = WEAPON_DEFS[w.type].base;
    const L = w.level - 1;
    const s = Object.assign({}, b);
    switch (w.type) {
      case "pistol":
        s.dmg = b.dmg + L * 5;
        s.count = b.count + Math.floor(L / 2) + player.stats.projAdd;
        s.cd = b.cd * Math.max(0.45, 1 - L * 0.08);
        s.pierce = b.pierce + Math.floor(L / 3);
        break;
      case "shotgun":
        s.dmg = b.dmg + L * 4;
        s.count = b.count + L + player.stats.projAdd;
        s.cd = b.cd * Math.max(0.5, 1 - L * 0.07);
        s.pierce = b.pierce + Math.floor(L / 2);
        break;
      case "orbit":
        s.dmg = b.dmg + L * 6;
        s.count = b.count + L;
        s.radius = (b.radius + L * 6) * player.stats.areaMul;
        s.rotSpeed = b.rotSpeed + L * 0.15;
        break;
      case "aura":
        s.dmg = b.dmg + L * 4;
        s.radius = (b.radius + L * 12) * player.stats.areaMul;
        s.tickRate = Math.max(0.18, b.tickRate - L * 0.03);
        break;
      case "laser":
        s.dmg = b.dmg + L * 12;
        s.count = b.count + Math.floor(L / 2);
        s.cd = b.cd * Math.max(0.4, 1 - L * 0.09);
        break;
    }
    s.dmg *= player.stats.dmgMul;
    if (s.cd !== undefined) s.cd *= player.stats.fireRateMul;
    if (s.speed !== undefined) s.speed *= player.stats.projSpeedMul;
    return s;
  }

  // Find nearest zombie to a point. Returns null if none.
  function nearestZombie(x, y, maxR) {
    let best = null, bestD = maxR ? maxR * maxR : Infinity;
    for (const z of zombies) {
      if (z.dead) continue;
      const d = dist2(x, y, z.x, z.y);
      if (d < bestD) { bestD = d; best = z; }
    }
    return best;
  }

  function spawnProjectile(x, y, angle, s, opts = {}) {
    projectiles.push({
      x, y,
      vx: Math.cos(angle) * s.speed,
      vy: Math.sin(angle) * s.speed,
      dmg: s.dmg,
      r: opts.r || 6,
      pierce: s.pierce || 1,
      life: opts.life || 1.4,
      hitSet: new Set(),
      kind: opts.kind || "bullet",
      color: opts.color || "#ffe96b",
    });
  }

  function fireWeapons(dt) {
    for (const w of player.weapons) {
      const s = weaponStats(w);
      switch (w.type) {
        case "pistol":
        case "laser": {
          w.timer -= dt;
          if (w.timer <= 0) {
            const target = nearestZombie(player.x, player.y);
            if (target) {
              w.timer = s.cd;
              const base = Math.atan2(target.y - player.y, target.x - player.x);
              const spread = w.type === "laser" ? 0.12 : 0.18;
              for (let i = 0; i < s.count; i++) {
                const off = (i - (s.count - 1) / 2) * spread;
                spawnProjectile(player.x, player.y, base + off, s, {
                  kind: w.type === "laser" ? "laser" : "bullet",
                  r: w.type === "laser" ? 4 : 6,
                  life: w.type === "laser" ? 0.6 : 1.4,
                  color: w.type === "laser" ? "#67e8ff" : "#ffe96b",
                });
              }
              spawnMuzzle(player.x, player.y, base);
            }
          }
          break;
        }
        case "shotgun": {
          w.timer -= dt;
          if (w.timer <= 0) {
            const target = nearestZombie(player.x, player.y, s.range);
            if (target) {
              w.timer = s.cd;
              const base = Math.atan2(target.y - player.y, target.x - player.x);
              for (let i = 0; i < s.count; i++) {
                const off = (Math.random() - 0.5) * s.spread + (i - (s.count - 1) / 2) * 0.05;
                spawnProjectile(player.x, player.y, base + off, s, { r: 5, life: 0.55, color: "#ffb24a" });
              }
              spawnMuzzle(player.x, player.y, base);
            }
          }
          break;
        }
        case "orbit": {
          w.angle += s.rotSpeed * dt;
          w.tick -= dt;
          const doDmg = w.tick <= 0;
          if (doDmg) w.tick = WEAPON_DEFS.orbit.base.tickRate;
          w.blades.length = 0;
          for (let i = 0; i < s.count; i++) {
            const a = w.angle + (i / s.count) * TAU;
            const bx = player.x + Math.cos(a) * s.radius;
            const by = player.y + Math.sin(a) * s.radius;
            w.blades.push({ x: bx, y: by });
            if (doDmg) {
              for (const z of zombies) {
                if (z.dead) continue;
                if (dist2(bx, by, z.x, z.y) < (z.r + 14) ** 2) {
                  hitZombie(z, s.dmg, (z.x - player.x), (z.y - player.y));
                }
              }
            }
          }
          break;
        }
        case "aura": {
          w.tick -= dt;
          if (w.tick <= 0) {
            w.tick = s.tickRate;
            for (const z of zombies) {
              if (z.dead) continue;
              if (dist2(player.x, player.y, z.x, z.y) < (s.radius + z.r) ** 2) {
                hitZombie(z, s.dmg, (z.x - player.x), (z.y - player.y));
              }
            }
          }
          w._radius = s.radius;
          break;
        }
      }
    }
  }

  // ---------- Zombie types ----------
  const ZOMBIE_TYPES = {
    walker: { hp: 18, speed: 52, dmg: 8, r: 15, color: "#6b8f3a", xp: 1, score: 1 },
    runner: { hp: 12, speed: 108, dmg: 6, r: 12, color: "#9fd44a", xp: 1, score: 2 },
    brute:  { hp: 95, speed: 38, dmg: 18, r: 26, color: "#4a6b2a", xp: 4, score: 5 },
    spitter:{ hp: 24, speed: 46, dmg: 7, r: 14, color: "#b07ad4", xp: 2, score: 3, ranged: true },
  };

  function spawnZombie(type) {
    const t = ZOMBIE_TYPES[type];
    // spawn just outside the screen, around the player
    const ang = Math.random() * TAU;
    const radius = Math.hypot(W, H) / 2 / 1 + rand(40, 120);
    const diff = 1 + world.time / 80; // scales hp/speed over time
    zombies.push({
      type, x: player.x + Math.cos(ang) * radius, y: player.y + Math.sin(ang) * radius,
      hp: t.hp * diff, maxHp: t.hp * diff,
      speed: t.speed * (1 + Math.min(0.4, world.time / 300)),
      dmg: t.dmg, r: t.r, color: t.color,
      xp: t.xp, score: t.score,
      hitFlash: 0, dead: false, atkCd: 0,
      ranged: !!t.ranged, shootCd: rand(1, 2.5),
      wobble: Math.random() * TAU,
    });
  }

  // ---------- Spawning director ----------
  let spawnAccumulator = 0;
  let bossTimer = 60; // first elite at 60s
  function updateDirector(dt) {
    // spawn rate ramps with time
    const t = world.time;
    const ratePerSec = 0.8 + t * 0.05;        // zombies/sec
    spawnAccumulator += ratePerSec * dt;
    while (spawnAccumulator >= 1) {
      spawnAccumulator -= 1;
      pickAndSpawn(t);
    }
    // periodic elite (brute) waves
    bossTimer -= dt;
    if (bossTimer <= 0) {
      bossTimer = 45;
      const n = 1 + Math.floor(t / 90);
      for (let i = 0; i < n; i++) spawnZombie("brute");
    }
  }
  function pickAndSpawn(t) {
    const roll = Math.random();
    if (t > 120 && roll < 0.12) spawnZombie("brute");
    else if (t > 30 && roll < 0.4) spawnZombie("runner");
    else if (t > 50 && roll < 0.55) spawnZombie("spitter");
    else spawnZombie("walker");
  }

  // ---------- Combat ----------
  function hitZombie(z, dmg, kx, ky) {
    let final = dmg;
    let crit = false;
    if (Math.random() < player.stats.critChance) { final *= 2; crit = true; }
    z.hp -= final;
    z.hitFlash = 0.12;
    spawnDamageText(z.x, z.y - z.r, Math.round(final), crit);
    // small knockback
    const len = Math.hypot(kx, ky) || 1;
    z.x += (kx / len) * 2;
    z.y += (ky / len) * 2;
    if (z.hp <= 0 && !z.dead) killZombie(z);
  }

  function killZombie(z) {
    z.dead = true;
    world.kills++;
    spawnBlood(z.x, z.y, z.color);
    // drop xp gem
    gems.push({ x: z.x, y: z.y, value: z.xp, r: 5 + Math.min(4, z.xp), vx: rand(-30, 30), vy: rand(-30, 30) });
    // small chance to drop health
    if (Math.random() < 0.025) {
      pickups.push({ x: z.x, y: z.y, kind: "health", r: 9, amount: 25 });
    }
  }

  function damagePlayer(amount) {
    if (player.iframe > 0) return;
    player.hp -= amount;
    player.iframe = 0.6;
    spawnBlood(player.x, player.y, "#e84545");
    flashScreen();
    if (player.hp <= 0) {
      player.hp = 0;
      gameOver();
    }
  }

  // ---------- Particles & FX ----------
  function spawnBlood(x, y, color) {
    const n = 8;
    for (let i = 0; i < n; i++) {
      const a = Math.random() * TAU, sp = rand(40, 180);
      particles.push({ x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, life: rand(0.3, 0.7), max: 0.7, r: rand(2, 5), color });
    }
  }
  function spawnMuzzle(x, y, angle) {
    particles.push({ x: x + Math.cos(angle) * 18, y: y + Math.sin(angle) * 18, vx: Math.cos(angle) * 60, vy: Math.sin(angle) * 60, life: 0.08, max: 0.08, r: 6, color: "#fff3a0" });
  }
  function spawnDamageText(x, y, val, crit) {
    damageTexts.push({ x: x + rand(-6, 6), y, val, life: 0.6, max: 0.6, crit });
  }
  let screenFlash = 0;
  function flashScreen() { screenFlash = 0.25; }

  // Enemy ranged projectiles reuse projectiles array with kind "spit"
  function spawnSpit(z) {
    const a = Math.atan2(player.y - z.y, player.x - z.x);
    const sp = 220;
    projectiles.push({
      x: z.x, y: z.y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp,
      dmg: z.dmg, r: 7, pierce: 1, life: 3, hitSet: new Set(),
      kind: "spit", color: "#c98bff", enemy: true,
    });
  }

  // ---------- Update loop ----------
  function update(dt) {
    world.time += dt;

    // --- player movement ---
    let mx = 0, my = 0;
    if (keys["w"] || keys["arrowup"]) my -= 1;
    if (keys["s"] || keys["arrowdown"]) my += 1;
    if (keys["a"] || keys["arrowleft"]) mx -= 1;
    if (keys["d"] || keys["arrowright"]) mx += 1;
    if (joy.active) { mx += joy.dx; my += joy.dy; }
    const ml = Math.hypot(mx, my);
    if (ml > 1) { mx /= ml; my /= ml; }
    if (mx !== 0) player.facing = mx < 0 ? -1 : 1;
    player.x += mx * player.speed * dt;
    player.y += my * player.speed * dt;
    player.moveX = mx; player.moveY = my;

    if (player.iframe > 0) player.iframe -= dt;
    if (player.regen > 0 && player.hp < player.maxHp) {
      player.hp = Math.min(player.maxHp, player.hp + player.regen * dt);
    }

    // --- director / spawning ---
    updateDirector(dt);

    // --- weapons ---
    fireWeapons(dt);

    // --- zombies AI ---
    for (const z of zombies) {
      if (z.dead) continue;
      const a = Math.atan2(player.y - z.y, player.x - z.x);
      z.wobble += dt * 6;
      const wob = Math.sin(z.wobble) * 0.12;
      const dz2 = dist2(z.x, z.y, player.x, player.y);

      if (z.ranged && dz2 < 360 * 360 && dz2 > 120 * 120) {
        // keep distance, shoot
        z.x += Math.cos(a) * z.speed * 0.3 * dt;
        z.y += Math.sin(a) * z.speed * 0.3 * dt;
        z.shootCd -= dt;
        if (z.shootCd <= 0) { z.shootCd = rand(1.6, 2.8); spawnSpit(z); }
      } else {
        z.x += Math.cos(a + wob) * z.speed * dt;
        z.y += Math.sin(a + wob) * z.speed * dt;
      }
      if (z.hitFlash > 0) z.hitFlash -= dt;

      // contact damage
      z.atkCd -= dt;
      if (dz2 < (z.r + player.r) ** 2) {
        if (z.atkCd <= 0) { damagePlayer(z.dmg); z.atkCd = 0.6; }
      }
    }
    // zombie-zombie separation (cheap)
    separateZombies();
    // cull dead
    zombies = zombies.filter((z) => !z.dead);

    // --- projectiles ---
    for (const p of projectiles) {
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.life -= dt;
      if (p.enemy) {
        if (dist2(p.x, p.y, player.x, player.y) < (p.r + player.r) ** 2) {
          damagePlayer(p.dmg); p.life = 0;
        }
      } else {
        for (const z of zombies) {
          if (z.dead || p.hitSet.has(z)) continue;
          if (dist2(p.x, p.y, z.x, z.y) < (p.r + z.r) ** 2) {
            hitZombie(z, p.dmg, p.vx, p.vy);
            p.hitSet.add(z);
            p.pierce--;
            if (p.pierce <= 0) { p.life = 0; break; }
          }
        }
      }
    }
    projectiles = projectiles.filter((p) => p.life > 0);

    // --- gems (xp) ---
    for (const g of gems) {
      // magnet
      const d2 = dist2(g.x, g.y, player.x, player.y);
      if (d2 < player.pickupRange ** 2) {
        const a = Math.atan2(player.y - g.y, player.x - g.x);
        const pull = 320;
        g.x += Math.cos(a) * pull * dt;
        g.y += Math.sin(a) * pull * dt;
      } else {
        g.vx *= 0.9; g.vy *= 0.9;
        g.x += g.vx * dt; g.y += g.vy * dt;
      }
      if (d2 < (player.r + 6) ** 2) { gainXp(g.value); g.taken = true; }
    }
    gems = gems.filter((g) => !g.taken);

    // --- pickups ---
    for (const pk of pickups) {
      if (dist2(pk.x, pk.y, player.x, player.y) < (player.r + pk.r) ** 2) {
        if (pk.kind === "health") player.hp = Math.min(player.maxHp, player.hp + pk.amount);
        pk.taken = true;
      }
    }
    pickups = pickups.filter((pk) => !pk.taken);

    // --- particles ---
    for (const pt of particles) {
      pt.life -= dt;
      pt.x += pt.vx * dt; pt.y += pt.vy * dt;
      pt.vx *= 0.92; pt.vy *= 0.92;
    }
    particles = particles.filter((pt) => pt.life > 0);

    for (const d of damageTexts) { d.life -= dt; d.y -= 28 * dt; }
    damageTexts = damageTexts.filter((d) => d.life > 0);

    if (screenFlash > 0) screenFlash -= dt;

    updateHUD();
  }

  // Light separation so zombies don't fully stack
  function separateZombies() {
    const n = zombies.length;
    for (let i = 0; i < n; i++) {
      const a = zombies[i];
      if (a.dead) continue;
      for (let j = i + 1; j < n; j++) {
        const b = zombies[j];
        if (b.dead) continue;
        const dx = b.x - a.x, dy = b.y - a.y;
        const min = a.r + b.r;
        const d2 = dx * dx + dy * dy;
        if (d2 < min * min && d2 > 0.001) {
          const d = Math.sqrt(d2);
          const push = (min - d) / 2;
          const ux = dx / d, uy = dy / d;
          a.x -= ux * push; a.y -= uy * push;
          b.x += ux * push; b.y += uy * push;
        }
      }
    }
  }

  // ---------- XP & Leveling ----------
  function gainXp(v) {
    player.xp += v;
    while (player.xp >= player.xpNext) {
      player.xp -= player.xpNext;
      player.level++;
      player.xpNext = Math.floor(5 + player.level * 3 + Math.pow(player.level, 1.55));
      openLevelUp();
    }
  }

  // ---------- Upgrade pool ----------
  function buildUpgradePool() {
    const pool = [];
    // New / upgrade weapons
    for (const type of Object.keys(WEAPON_DEFS)) {
      const def = WEAPON_DEFS[type];
      const owned = getWeapon(type);
      if (owned) {
        if (owned.level < 8) {
          pool.push({
            icon: def.icon, title: `${def.name} 強化`, desc: weaponUpgradeDesc(type),
            lvl: `Lv ${owned.level} → ${owned.level + 1}`, weight: 10,
            apply: () => { owned.level++; },
          });
        }
      } else if (player.weapons.length < 6) {
        pool.push({
          icon: def.icon, title: `新武器：${def.name}`, desc: weaponNewDesc(type),
          lvl: "NEW", weight: 6,
          apply: () => addWeapon(type),
        });
      }
    }
    // Passive stats
    const passives = [
      { icon: "❤️", title: "強健體魄", desc: "最大生命 +20，並回滿差額", lvl: "+20 HP", weight: 9,
        apply: () => { player.maxHp += 20; player.hp += 20; } },
      { icon: "👟", title: "疾步靴", desc: "移動速度 +12%", lvl: "+12%", weight: 8,
        apply: () => { player.speed *= 1.12; } },
      { icon: "🗡️", title: "利刃", desc: "全武器傷害 +15%", lvl: "+15%", weight: 9,
        apply: () => { player.stats.dmgMul *= 1.15; } },
      { icon: "⏱️", title: "急速裝填", desc: "攻擊速度 +12%", lvl: "+12%", weight: 8,
        apply: () => { player.stats.fireRateMul *= 0.88; } },
      { icon: "🧲", title: "磁力場", desc: "拾取範圍 +40%", lvl: "+40%", weight: 6,
        apply: () => { player.pickupRange *= 1.4; } },
      { icon: "💉", title: "再生", desc: "每秒回復 +1 生命", lvl: "+1/s", weight: 6,
        apply: () => { player.regen += 1; } },
      { icon: "🎯", title: "精準", desc: "暴擊率 +8%", lvl: "+8%", weight: 6,
        apply: () => { player.stats.critChance += 0.08; } },
      { icon: "➕", title: "多重彈幕", desc: "槍械投射物 +1", lvl: "+1", weight: 5,
        apply: () => { player.stats.projAdd += 1; } },
      { icon: "🌐", title: "領域擴張", desc: "範圍類武器 +18%", lvl: "+18%", weight: 5,
        apply: () => { player.stats.areaMul *= 1.18; } },
    ];
    pool.push(...passives);
    return pool;
  }
  function weaponUpgradeDesc(type) {
    return ({
      pistol: "傷害提升，並逐步增加彈數與穿透",
      shotgun: "更多彈丸、更高傷害與穿透",
      orbit: "更多刀刃、更大半徑與傷害",
      aura: "更大範圍、更高頻率傷害",
      laser: "高傷穿透雷射，傷害大幅提升",
    })[type];
  }
  function weaponNewDesc(type) {
    return ({
      pistol: "自動朝最近敵人射擊",
      shotgun: "近距離扇形散射，清群利器",
      orbit: "環繞自身的旋轉刀刃",
      aura: "持續灼燒周圍敵人",
      laser: "高速穿透所有敵人的雷射",
    })[type];
  }

  function pickUpgrades(n) {
    const pool = buildUpgradePool();
    const chosen = [];
    const total = () => pool.reduce((s, u) => s + u.weight, 0);
    for (let i = 0; i < n && pool.length; i++) {
      let r = Math.random() * total();
      let idx = 0;
      for (let j = 0; j < pool.length; j++) {
        r -= pool[j].weight;
        if (r <= 0) { idx = j; break; }
      }
      chosen.push(pool[idx]);
      pool.splice(idx, 1);
    }
    return chosen;
  }

  // ---------- Rendering ----------
  function draw() {
    ctx.clearRect(0, 0, W, H);

    // camera transform: center on player
    const camX = W / 2 - player.x;
    const camY = H / 2 - player.y;

    drawGround(camX, camY);

    ctx.save();
    ctx.translate(camX, camY);

    // gems
    for (const g of gems) {
      ctx.fillStyle = "#5fd0ff";
      ctx.beginPath();
      ctx.moveTo(g.x, g.y - g.r);
      ctx.lineTo(g.x + g.r, g.y);
      ctx.lineTo(g.x, g.y + g.r);
      ctx.lineTo(g.x - g.r, g.y);
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,0.6)"; ctx.lineWidth = 1; ctx.stroke();
    }
    // pickups
    for (const pk of pickups) {
      if (pk.kind === "health") {
        ctx.fillStyle = "#ff5b5b";
        ctx.fillRect(pk.x - 3, pk.y - 9, 6, 18);
        ctx.fillRect(pk.x - 9, pk.y - 3, 18, 6);
      }
    }

    // aura visual (under zombies)
    for (const w of player.weapons) {
      if (w.type === "aura" && w._radius) {
        const grd = ctx.createRadialGradient(player.x, player.y, 0, player.x, player.y, w._radius);
        grd.addColorStop(0, "rgba(150,80,200,0.05)");
        grd.addColorStop(0.7, "rgba(150,80,200,0.18)");
        grd.addColorStop(1, "rgba(150,80,200,0.02)");
        ctx.fillStyle = grd;
        ctx.beginPath(); ctx.arc(player.x, player.y, w._radius, 0, TAU); ctx.fill();
      }
    }

    // zombies
    for (const z of zombies) drawZombie(z);

    // projectiles
    for (const p of projectiles) drawProjectile(p);

    // orbit blades (over zombies)
    for (const w of player.weapons) {
      if (w.type === "orbit") {
        for (const b of w.blades) {
          ctx.save();
          ctx.translate(b.x, b.y);
          ctx.rotate(w.angle * 3);
          ctx.fillStyle = "#dfe9ff";
          ctx.beginPath();
          ctx.moveTo(0, -12); ctx.lineTo(4, 0); ctx.lineTo(0, 12); ctx.lineTo(-4, 0);
          ctx.closePath(); ctx.fill();
          ctx.strokeStyle = "rgba(120,180,255,0.8)"; ctx.lineWidth = 1.5; ctx.stroke();
          ctx.restore();
        }
      }
    }

    // player
    drawPlayer();

    // particles
    for (const pt of particles) {
      ctx.globalAlpha = clamp(pt.life / pt.max, 0, 1);
      ctx.fillStyle = pt.color;
      ctx.beginPath(); ctx.arc(pt.x, pt.y, pt.r, 0, TAU); ctx.fill();
    }
    ctx.globalAlpha = 1;

    // damage texts
    for (const d of damageTexts) {
      ctx.globalAlpha = clamp(d.life / d.max, 0, 1);
      ctx.fillStyle = d.crit ? "#ffd34a" : "#ffffff";
      ctx.font = (d.crit ? "bold 18px " : "bold 14px ") + "monospace";
      ctx.textAlign = "center";
      ctx.fillText(d.val, d.x, d.y);
    }
    ctx.globalAlpha = 1;

    ctx.restore();

    // screen-edge danger flash
    if (screenFlash > 0) {
      ctx.fillStyle = `rgba(180,0,0,${screenFlash * 0.6})`;
      ctx.fillRect(0, 0, W, H);
    }
  }

  function drawGround(camX, camY) {
    // dark grid that scrolls with camera
    const grid = 64;
    ctx.fillStyle = "#12180e";
    ctx.fillRect(0, 0, W, H);
    ctx.strokeStyle = "rgba(255,255,255,0.035)";
    ctx.lineWidth = 1;
    const ox = ((camX % grid) + grid) % grid;
    const oy = ((camY % grid) + grid) % grid;
    ctx.beginPath();
    for (let x = ox; x < W; x += grid) { ctx.moveTo(x, 0); ctx.lineTo(x, H); }
    for (let y = oy; y < H; y += grid) { ctx.moveTo(0, y); ctx.lineTo(W, y); }
    ctx.stroke();
  }

  function drawZombie(z) {
    const flash = z.hitFlash > 0;
    // body
    ctx.fillStyle = flash ? "#ffffff" : z.color;
    ctx.beginPath(); ctx.arc(z.x, z.y, z.r, 0, TAU); ctx.fill();
    // darker outline
    ctx.strokeStyle = "rgba(0,0,0,0.4)"; ctx.lineWidth = 2; ctx.stroke();
    // eyes (toward player)
    const a = Math.atan2(player.y - z.y, player.x - z.x);
    const ex = Math.cos(a) * z.r * 0.4, ey = Math.sin(a) * z.r * 0.4;
    const eo = z.r * 0.28;
    const perp = a + Math.PI / 2;
    ctx.fillStyle = flash ? "#000" : "#ffea00";
    for (const s of [-1, 1]) {
      ctx.beginPath();
      ctx.arc(z.x + ex + Math.cos(perp) * eo * s, z.y + ey + Math.sin(perp) * eo * s, Math.max(2, z.r * 0.12), 0, TAU);
      ctx.fill();
    }
    // hp bar for tougher enemies
    if (z.maxHp > 30 && z.hp < z.maxHp) {
      const w = z.r * 2, h = 4;
      ctx.fillStyle = "rgba(0,0,0,0.6)";
      ctx.fillRect(z.x - w / 2, z.y - z.r - 9, w, h);
      ctx.fillStyle = "#ff5b5b";
      ctx.fillRect(z.x - w / 2, z.y - z.r - 9, w * (z.hp / z.maxHp), h);
    }
  }

  function drawProjectile(p) {
    if (p.kind === "laser") {
      ctx.strokeStyle = p.color; ctx.lineWidth = 4; ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      ctx.lineTo(p.x - p.vx * 0.02, p.y - p.vy * 0.02);
      ctx.stroke();
      ctx.shadowBlur = 0;
    } else {
      ctx.fillStyle = p.color;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, TAU); ctx.fill();
      if (p.enemy) { ctx.strokeStyle = "rgba(255,255,255,0.5)"; ctx.lineWidth = 1; ctx.stroke(); }
    }
  }

  function drawPlayer() {
    const x = player.x, y = player.y;
    // shadow
    ctx.fillStyle = "rgba(0,0,0,0.35)";
    ctx.beginPath(); ctx.ellipse(x, y + player.r * 0.8, player.r * 0.9, player.r * 0.4, 0, 0, TAU); ctx.fill();
    // body
    const blink = player.iframe > 0 && Math.floor(player.iframe * 20) % 2 === 0;
    ctx.fillStyle = blink ? "#ffffff" : "#4aa3dc";
    ctx.beginPath(); ctx.arc(x, y, player.r, 0, TAU); ctx.fill();
    ctx.strokeStyle = "#0d2c40"; ctx.lineWidth = 2.5; ctx.stroke();
    // visor facing direction
    ctx.fillStyle = "#eaffff";
    ctx.fillRect(x + player.facing * 4 - 3, y - 4, 8, 6);
  }

  // ---------- HUD ----------
  const elHpFill = document.getElementById("hp-fill");
  const elHpText = document.getElementById("hp-text");
  const elXpFill = document.getElementById("xp-fill");
  const elTimer = document.getElementById("timer");
  const elKills = document.getElementById("kills");
  const elLevel = document.getElementById("level");

  function updateHUD() {
    const hpPct = clamp(player.hp / player.maxHp, 0, 1) * 100;
    elHpFill.style.width = hpPct + "%";
    elHpText.textContent = `${Math.ceil(player.hp)}/${player.maxHp}`;
    elXpFill.style.width = clamp(player.xp / player.xpNext, 0, 1) * 100 + "%";
    const m = Math.floor(world.time / 60), s = Math.floor(world.time % 60);
    elTimer.textContent = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    elKills.textContent = `☠ ${world.kills}`;
    elLevel.textContent = `Lv ${player.level}`;
  }

  // ---------- Screens ----------
  const screenStart = document.getElementById("screen-start");
  const screenLevelup = document.getElementById("screen-levelup");
  const screenOver = document.getElementById("screen-over");
  const hud = document.getElementById("hud");
  const btnPause = document.getElementById("btn-pause");
  const upgradeCards = document.getElementById("upgrade-cards");

  function openLevelUp() {
    state = GameState.LEVELUP;
    const options = pickUpgrades(3);
    upgradeCards.innerHTML = "";
    options.forEach((u) => {
      const card = document.createElement("div");
      card.className = "upgrade-card";
      card.innerHTML = `
        <div class="upgrade-icon">${u.icon}</div>
        <div class="upgrade-text"><b>${u.title}</b><small>${u.desc}</small></div>
        <div class="upgrade-lvl">${u.lvl}</div>`;
      card.addEventListener("click", () => {
        u.apply();
        screenLevelup.classList.add("hidden");
        // there may be multiple pending levels; resume play (gainXp loop handles)
        state = GameState.PLAYING;
      });
      upgradeCards.appendChild(card);
    });
    screenLevelup.classList.remove("hidden");
  }

  function gameOver() {
    state = GameState.OVER;
    const m = Math.floor(world.time / 60), s = Math.floor(world.time % 60);
    document.getElementById("final-stats").innerHTML = `
      存活時間：<b>${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}</b><br>
      擊殺數：<b>${world.kills}</b><br>
      等級：<b>${player.level}</b>`;
    screenOver.classList.remove("hidden");
    btnPause.classList.add("hidden");
    joyEnd(); joyEl.classList.add("hidden");
  }

  function togglePause() {
    if (state === GameState.PLAYING) { state = GameState.PAUSED; btnPause.textContent = "▶"; }
    else if (state === GameState.PAUSED) { state = GameState.PLAYING; btnPause.textContent = "⏸"; }
  }

  // ---------- Start / Reset ----------
  function startGame() {
    player = makePlayer();
    zombies = []; projectiles = []; gems = []; particles = []; pickups = []; damageTexts = [];
    world.time = 0; world.kills = 0;
    spawnAccumulator = 0; bossTimer = 60;
    addWeapon("pistol"); // starting weapon
    state = GameState.PLAYING;

    screenStart.classList.add("hidden");
    screenOver.classList.add("hidden");
    screenLevelup.classList.add("hidden");
    hud.classList.remove("hidden");
    btnPause.classList.remove("hidden");
    btnPause.textContent = "⏸";
    if (isTouch) joyEl.classList.remove("hidden");
    updateHUD();
  }

  document.getElementById("btn-start").addEventListener("click", startGame);
  document.getElementById("btn-restart").addEventListener("click", startGame);
  btnPause.addEventListener("click", togglePause);

  // ---------- Main loop ----------
  let last = performance.now();
  function loop(now) {
    let dt = (now - last) / 1000;
    last = now;
    if (dt > 0.05) dt = 0.05; // clamp big frame gaps (tab switch)

    if (state === GameState.PLAYING) update(dt);
    if (state !== GameState.MENU) draw();

    // pause hint overlay
    if (state === GameState.PAUSED) {
      ctx.fillStyle = "rgba(0,0,0,0.5)"; ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = "#fff"; ctx.font = "bold 28px sans-serif"; ctx.textAlign = "center";
      ctx.fillText("已暫停", W / 2, H / 2);
      ctx.font = "14px sans-serif"; ctx.fillStyle = "#9fb38c";
      ctx.fillText("按 Esc 或 ▶ 繼續", W / 2, H / 2 + 28);
    }

    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
})();
