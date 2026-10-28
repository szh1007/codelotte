/* 高并发面试课 · 容量估算计算器
   用法：
   <div class="calculator" data-calculator>
     输入：<input data-input="qps"> 等
     输出：<strong data-output="concurrency"></strong> 等
   </div>
*/
(function () {
  "use strict";

  function toNumber(value, fallback) {
    var n = parseFloat(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function fmt(n) {
    return new Intl.NumberFormat("zh-CN", {
      maximumFractionDigits: 1,
      minimumFractionDigits: 0
    }).format(n);
  }

  document.querySelectorAll("[data-calculator]").forEach(function (calc) {
    var inputs = Array.prototype.slice.call(calc.querySelectorAll("input[data-input]"));
    var outputs = {};
    calc.querySelectorAll("[data-output]").forEach(function (el) {
      outputs[el.getAttribute("data-output")] = el;
    });

    function get(name, fallback) {
      var el = calc.querySelector('[data-input="' + name + '"]');
      return el ? toNumber(el.value, fallback) : fallback;
    }

    function set(name, text) {
      if (outputs[name]) {
        outputs[name].textContent = text;
      }
    }

    function update() {
      var qps = Math.max(0, get("qps", 1000));
      var latency = Math.max(0, get("latency", 100));
      var readRatio = Math.min(100, Math.max(0, get("readRatio", 90))) / 100;
      var hit = Math.min(100, Math.max(0, get("hit", 95))) / 100;

      var concurrency = (qps * latency) / 1000;
      var readQps = qps * readRatio;
      var cacheQps = readQps * hit;
      var dbReadQps = readQps * (1 - hit);
      var dbWriteQps = qps * (1 - readRatio);
      var dbTotalQps = dbReadQps + dbWriteQps;

      set("concurrency", fmt(concurrency) + " 并发");
      set("readQps", fmt(readQps) + " QPS");
      set("cacheQps", fmt(cacheQps) + " QPS");
      set("dbReadQps", fmt(dbReadQps) + " QPS");
      set("dbWriteQps", fmt(dbWriteQps) + " QPS");
      set("dbTotalQps", fmt(dbTotalQps) + " QPS");
    }

    inputs.forEach(function (input) {
      input.addEventListener("input", update);
      input.addEventListener("change", update);
    });

    update();
  });
})();
