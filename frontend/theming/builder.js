const builder = (definitions = {}) => {
  const proto = {
    s: function(prop, value) {
      if (prop instanceof Object) {
        for (var name in prop) {
          defaultRules.s.call(this, name, prop[name]);
        }
      } else {
        this[prop] = value instanceof Object ? value.obj || value : value;
      }
    },
    hover: function(value) {
      proto.s.call(this, ":hover", value);
    },

    focus: function(value) {
      proto.s.call(this, ":focus", value);
    }
  };

  const checkStart = function(name, fn) {
    return function() {
      if (this === proto) {
        const instance = Object.create(proto);
        if (typeof instance[name] === "function") {
          return instance[name].apply(instance, arguments);
        }
        return instance[name];
      }
      return fn.apply(this, arguments);
    };
  };

  const defineAtom = function(name) {
    const definition = definitions[name];

    if (typeof definition === "function") {
      if (definition.length) {
        // definition: (argument) => ({})
        Object.defineProperty(proto, name, {
          enumerable: false,
          value: checkStart(name, function() {
            Object.assign(this, definition.apply(this, arguments));
            return this;
          })
        });
      } else {
        // definition: () => ({})
        Object.defineProperty(proto, name, {
          enumerable: false,
          get: checkStart(name, function() {
            Object.assign(this, definition.call(this));
            return this;
          })
        });
      }
    } else {
      // definition: "value"
      // proto[name] = checkStart(name, function(value) {
      // ;
      // Object.defineProperty(proto, name, {
      //   enumerable: false,
      //   get: checkStart(name, function(value) {
      //     this["" + definition] = value;
      //     // Object.assign(this, definition.call(this));
      //     return this;
      //   })
      // });
      return this;
      // });
    }
  };

  for (const name in definitions) defineAtom(name);

  return proto;
};

const theme = builder({
  reset: {
    appareance: "none"
  },
  bg: value => ({
    "background-color": value
  }),
  text: value => ({
    color: value
  })
});

console.log(
  theme
    .text("red")
    .text("blue")
    .bg("blue")
);
console.log(theme.hover(theme.text("red")));
