# Clientes

[← Volver al manual](README.md)

Los clientes se comparten entre todas las sucursales. En el giro Salud se llaman **pacientes**.

## Registrar un cliente

**Clientes → Nuevo cliente.** Datos:

- **Nombre completo** y **teléfono** (10 dígitos) son obligatorios.
- Teléfono adicional, correo, empresa y dirección son opcionales.
- **Límite de crédito:** lo máximo que puede deber. 0 = sin crédito. Solo quien tiene permiso de crédito lo puede asignar.
- **Lista de precios:** si el cliente compra con precios especiales (mayoreo, cliente frecuente).
- **Datos adicionales:** los campos propios del negocio que se definen en Configuración (por ejemplo, fecha de nacimiento o alergias).

Si ya existe otro cliente con el mismo teléfono, el sistema avisa para evitar duplicados.

## La ficha del cliente

Al abrir un cliente ves:

- **Contacto** y **datos adicionales**.
- **Crédito:** límite, cuánto debe, cuánto tiene disponible y cuánto debe en esta sucursal. Si no tiene crédito, **Asignar límite de crédito**.
- **Citas** (o consultas, o eventos): sus citas, y **Agendar** para crear una nueva sin salir de la ficha.
- **Compras:** sus últimas ventas en esta sucursal, con lo que debe en cada una, y **Ver todas sus ventas**.
- **Paquetes y membresías** que ha comprado.
- **Expediente clínico** (solo giro Salud, con permiso).
- **Historial de cambios** de sus datos.

**Editar** cambia sus datos. Si bajas su límite por debajo de lo que debe, el sistema avisa: no podrá comprar a crédito hasta bajar su deuda.

## Abonos

Para registrar un pago de lo que el cliente debe en esta sucursal:

1. En la tarjeta **Crédito**, pulsa **Abonar**.
2. Elige la forma de pago y el monto (viene lleno con lo que debe). Con efectivo, puedes escribir lo recibido para ver el cambio.
3. **Registrar abono.**

El abono se reparte entre sus ventas pendientes, de la más antigua a la más reciente, y el sistema dice a qué folios se aplicó. No se puede abonar más de lo que debe. Necesitas una caja ocupada.

El abono de una cita o evento (varias formas de pago a la vez) se hace desde la cita; ver [Citas y eventos](citas-y-eventos.md#anticipos-y-saldo).

## Paquetes y membresías

Se configuran en el producto (ver [Productos](productos.md#paquetes-y-membresías)) y el cliente los obtiene al comprarlos:

- **Paquete:** un número de sesiones de un servicio, con o sin vencimiento. Al vender ese servicio al cliente aparece **Usar paquete (quedan N)** y se cobra en $0.
- **Membresía:** una vigencia (por ejemplo 30 días) y, si se quiere, una lista de precios especiales mientras esté vigente. Al renovarla, la nueva vigencia empieza cuando termina la anterior. Las membresías por vencer en los próximos 7 días se avisan en **Clientes**.

## Eliminar y restaurar

En la lista de clientes, el botón de eliminar quita al cliente de las búsquedas. Sus ventas y cotizaciones anteriores lo siguen mostrando. No se puede eliminar a un cliente que todavía debe. Para restaurarlo, abre su ficha y pulsa **Restaurar cliente**.
