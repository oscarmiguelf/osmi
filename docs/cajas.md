# Cajas y corte de caja

[← Volver al manual](README.md)

Cada sucursal tiene una o varias cajas. Una caja guarda el saldo de cada forma de pago (efectivo, tarjeta, transferencia) y todos sus movimientos.

## Ocupar y liberar

- **Ocupar caja:** la tomas para tu turno. Mientras la tengas, tus ventas, abonos, gastos y retiros salen o entran de ella. Una persona solo puede ocupar una caja a la vez, y una caja la ocupa una sola persona.
- **Liberar caja:** la sueltas para que otra persona pueda usarla. Si terminaste tu turno, mejor haz el **corte**: también libera la caja.

Un **supervisor** (con permiso de editar cajas) puede liberar la caja de alguien que olvidó hacerlo, y puede registrar movimientos y hacer cortes en cajas que ocupa otra persona.

## La pantalla de una caja

En **Cajas → la caja** ves:

- **Saldo en caja** por cada forma de pago.
- **Movimientos:** ventas, abonos, devoluciones, entradas, retiros, gastos, compras y cortes, con el saldo después de cada uno. Se pueden filtrar por tipo.
- **Cortes:** el historial de cortes.

## Entradas y retiros

- **Entrada:** dinero que metes a la caja (por ejemplo, el fondo para dar cambio).
- **Retiro:** dinero que sacas (por ejemplo, un depósito al banco). Pide una nota y no puede ser mayor que el saldo de esa forma de pago.

Los pagos de gastos y compras desde caja se registran en [Gastos](gastos.md) y [Compras](inventario.md#compras), y salen de la caja solos.

## Corte de caja

El corte cierra tu turno. Lo hace quien ocupa la caja o un supervisor.

1. En tu caja, pulsa **Hacer corte**.
2. **Cuenta** lo que hay de cada forma de pago y escríbelo: el efectivo, los vouchers de tarjeta, las transferencias. Junto a cada una ves la **diferencia** contra lo que el sistema esperaba. Todas las formas de pago que tienen saldo deben contarse.
3. **Retiro de corte (opcional):** si sacas efectivo al cerrar, escribe el monto y su **razón** (si la dejas vacía queda "Retiro de corte"). Puede ser $0; no puede ser mayor que el efectivo contado.
4. Revisa **Quedará en caja (efectivo)**: es el efectivo con el que empieza el siguiente turno.
5. Pulsa **Guardar corte**.

### Qué hace el corte

- **El efectivo** queda en lo que contaste menos el retiro. Si había faltante o sobrante, se registra solo como movimiento **Corte** ("Diferencia del corte").
- **Lo que no es efectivo** (tarjeta, transferencia) vuelve a **$0**, porque ya se contó y se entregó.
- **La caja queda libre.** Para volver a cobrar en ella hay que ocuparla de nuevo.

Ejemplo: se esperaban $500 en efectivo, se contaron $480 y se retiran $300 para depositar. El corte registra un faltante de $20 y quedan $180 en caja. La tarjeta, aunque tuviera $150, vuelve a $0.

El historial de cortes muestra, por cada corte, lo esperado, lo contado, la diferencia y el retiro con su razón.

## Formas de pago

Las formas de pago (efectivo, tarjeta, transferencia, a crédito) se activan o desactivan desde **Cajas**, con permiso de supervisor. Solo las activas aparecen al cobrar. **A crédito** no mueve dinero de la caja: es lo que el cliente queda debiendo. Las formas de pago se pueden renombrar sin problema.

## Crear y eliminar cajas

Con el permiso correspondiente, **Cajas** permite crear una caja, cambiarle el nombre o eliminarla. No se puede eliminar una caja ocupada o con dinero. Sus movimientos y cortes se conservan.
