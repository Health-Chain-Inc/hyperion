/* Hyperion landing: progressive enhancement only.
   Everything degrades gracefully: with JS off, content is fully visible and usable. */
(function () {
  "use strict";
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* 1) Scroll-reveal with staggered delay (IntersectionObserver) */
  var revealEls = document.querySelectorAll(".reveal-on-scroll");
  if (reduce || !("IntersectionObserver" in window)) {
    revealEls.forEach(function (el) { el.classList.add("in"); });
  } else {
    var io = new IntersectionObserver(function (entries, obs) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var group = Array.prototype.slice.call(entry.target.parentNode.children);
        var i = group.indexOf(entry.target);
        entry.target.style.setProperty("--sd", Math.min(i, 6) * 80 + "ms");
        entry.target.classList.add("in");
        obs.unobserve(entry.target);
      });
    }, { threshold: 0.15, rootMargin: "0px 0px -8% 0px" });
    revealEls.forEach(function (el) { io.observe(el); });
  }

  /* 2) Copy-to-clipboard on code cards */
  document.querySelectorAll(".copy-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var sel = btn.getAttribute("data-copy-target");
      var target = sel && document.querySelector(sel);
      if (!target) return;
      var text = target.innerText.replace(/ /g, " ");
      var done = function () {
        var label = btn.textContent;
        btn.textContent = "Copied"; btn.classList.add("copied");
        setTimeout(function () { btn.textContent = label; btn.classList.remove("copied"); }, 1600);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(function () {});
      } else {
        var ta = document.createElement("textarea");
        ta.value = text; document.body.appendChild(ta); ta.select();
        try { document.execCommand("copy"); done(); } catch (e) {}
        document.body.removeChild(ta);
      }
    });
  });

  /* 3) Subtle hero-glow parallax (skipped under reduced-motion) */
  if (!reduce) {
    var glow = document.querySelector(".hero-glow");
    if (glow) {
      var ticking = false;
      window.addEventListener("scroll", function () {
        if (ticking) return;
        ticking = true;
        window.requestAnimationFrame(function () {
          var y = window.scrollY || 0;
          if (y < window.innerHeight * 2) glow.style.transform = "translateY(" + (y * 0.28).toFixed(1) + "px)";
          ticking = false;
        });
      }, { passive: true });
    }
  }
})();
