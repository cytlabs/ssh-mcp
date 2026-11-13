import { h, ref } from "vue";
import Button from "primevue/button";
import InputText from "primevue/inputtext";

function field(label, name, value, attrs = {}) {
  return h("label", [label, h(InputText, {
    name, modelValue: value.value, "onUpdate:modelValue": text => { value.value = text; }, ...attrs,
  })]);
}

export default {
  props: ["account", "saveProfile", "saveSecurity"],
  setup(props) {
    const nickname = ref(props.account.nickname || ""), username = ref(props.account.username);
    const current = ref(""), next = ref(""), confirm = ref("");

    function form(id, title, button, submit, contents) {
      const pending = ref(false), message = ref("");
      async function onSubmit(event) {
        event.preventDefault();
        if (pending.value) return;
        pending.value = true;
        try { message.value = await submit(); }
        catch (error) { message.value = error.message; }
        finally { pending.value = false; }
      }
      return () => h("form", { id, class: "account-settings", onSubmit }, [
        h("h2", title), ...contents(),
        h(Button, { class: "primary", type: "submit", label: button, disabled: pending.value }),
        h("p", { role: "status" }, message.value),
      ]);
    }
    const profile = form("profile-form", "个人资料", "保存昵称", async () => {
      nickname.value = await props.saveProfile(nickname.value);
      return "昵称已保存。";
    }, () => [
      field("昵称", "nickname", nickname, { maxlength: 64, autocomplete: "nickname" }),
      h("small", "显示在控制台和新的命令审计记录中。"),
    ]);
    const security = form("security-form", "登录与安全", "保存更改", async () => {
      if (next.value !== confirm.value) return "两次输入的新密码不一致。";
      const body = { username: username.value.trim(), current_password: current.value };
      if (next.value) body.new_password = next.value;
      await props.saveSecurity(body);
      current.value = next.value = confirm.value = "";
      return "账号设置已保存。";
    }, () => [
      field("登录用户名", "username", username, { required: true, maxlength: 128, autocomplete: "username" }),
      field("当前密码", "current", current, { required: true, type: "password", autocomplete: "current-password" }),
      field("新密码（选填）", "next", next, { type: "password", minlength: 12, maxlength: 256, autocomplete: "new-password" }),
      field("确认新密码", "confirm", confirm, { type: "password", autocomplete: "new-password" }),
      h("small", "修改密码后，其他浏览器需重新登录，已授权的 MCP 客户端需重新授权。"),
    ]);
    return () => [profile(), security()];
  },
};
