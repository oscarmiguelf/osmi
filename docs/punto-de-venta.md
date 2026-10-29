# Punto de venta

[← Volver al manual](README.md)

El punto de venta es la pantalla de inicio de quien cobra. También se abre desde **Ventas → Nueva venta**.

## Antes de cobrar: ocupa una caja

Si no tienes una caja ocupada, el punto de venta te muestra las cajas libres de la sucursal. Pulsa **Ocupar** en una. Mientras la tengas, las ventas y los abonos que cobres entran a esa caja. Más detalles en [Cajas y corte de caja](cajas.md).

## Cobrar una venta

1. **Agrega productos.** Escanea el código de barras (y Enter) o escribe al menos dos letras del nombre y elige el producto. Puedes cambiar la cantidad de cada renglón o quitarlo.
2. **Cliente (opcional).** Búscalo por nombre, empresa o teléfono. Es necesario para vender a crédito, para usar paquetes del cliente y para aplicar sus precios especiales (lista de precios o membresía).
3. Pulsa **Cobrar** y elige cómo paga:
   - **Efectivo:** escribe lo **recibido** y el sistema calcula el **cambio** a entregar.
   - **Tarjeta o transferencia:** puedes anotar la referencia (autorización o folio).
   - **Varias formas de pago:** reparte el total entre efectivo, tarjeta, etc.
   - **A crédito:** la parte que no se paga queda como deuda del cliente (ver abajo).
4. Confirma. Aparece **Venta cobrada** con su folio y el cambio, y el punto de venta queda listo para la siguiente.

Los precios los pone el sistema: el precio del producto, el de la lista de precios del cliente o el de su membresía. No se escriben a mano.

## Descuentos y promociones

- **Promociones:** si un producto tiene una promoción vigente (por ejemplo 15 % menos o un 3x2), el punto de venta la ofrece en ese renglón. Ver [Promociones](promociones.md).
- **Descuento por renglón:** un monto menos en ese producto. Un renglón lleva promoción o descuento, no los dos.
- **Descuento a toda la venta:** se reparte entre los renglones al calcular el IVA y las devoluciones.

## Vender a crédito

Elige al cliente y, al cobrar, pon la parte que debe con **A crédito**. El cliente necesita un **límite de crédito** suficiente (se asigna en su ficha). Si se pasa del límite, el sistema avisa cuánto tiene disponible.

La venta queda **Con saldo** hasta que el cliente termine de pagar con abonos; ver [Clientes → Abonos](clientes.md#abonos) y [Ventas → Por cobrar](ventas.md#por-cobrar).

## Apartados

Para que el cliente se lleve los productos cuando termine de pagar, marca **Apartar** en los renglones (o **Apartar: entregar cuando termine de pagar** para todos). Los productos apartados se descuentan de la existencia para que nadie más los venda, y quedan en **Ventas → Por entregar** hasta que se entregan.

## Paquetes y membresías del cliente

Si el cliente compró un paquete de sesiones (por ejemplo 5 masajes), al agregar ese servicio aparece **Usar paquete (quedan N)**: el renglón se cobra en $0 y se descuenta una sesión. Si tiene una membresía vigente con precios especiales, esos precios se aplican solos. Ver [Clientes → Paquetes y membresías](clientes.md#paquetes-y-membresías).

## Cobrar una cotización o una cita

- **Cotización:** desde la cotización, **Convertir en venta**. El punto de venta se abre con sus productos y respeta los precios cotizados. Ver [Cotizaciones](cotizaciones.md).
- **Cita sin venta todavía:** desde la cita, **Cobrar** abre el punto de venta con su cliente y sus servicios. Normalmente las citas con servicios ya tienen su venta desde que se agendaron; ver [Citas y eventos](citas-y-eventos.md).

## El ticket

Al abrir una venta (**Ventas → la venta**) tienes:

- **Imprimir:** ticket de 80 mm.
- **Enviar por WhatsApp:** en el celular comparte el PDF del ticket; en la computadora descarga el PDF y abre el chat del cliente con un mensaje listo para que lo adjuntes.
- **Descargar PDF.**

## Si no hay existencia

El sistema no deja vender más de lo que hay en la sucursal (los servicios no llevan existencia; los kits descuentan sus componentes). Si falta, avisa qué producto y cuántos hay.

## Si se cae internet

Ver [Vender sin conexión](venta-sin-conexion.md).
