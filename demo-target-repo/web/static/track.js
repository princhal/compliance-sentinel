export function onCheckout(user, orderId) {
  console.log("checkout", user.email, user.card_number);
  console.log("checkout complete", orderId);
}
