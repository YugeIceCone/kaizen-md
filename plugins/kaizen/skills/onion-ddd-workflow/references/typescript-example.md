# Onion Architecture in TypeScript / Node

Concrete mapping of the four layers onto a TypeScript codebase using Express for the presentation layer and an in-memory repository (swap for Prisma/TypeORM in production).

## Domain (`src/modules/users/domain/`)

```ts
// value_objects/user_id.ts
import { randomUUID } from "node:crypto";

export class UserId {
  private constructor(private readonly value: string) {}
  static fresh(): UserId { return new UserId(randomUUID()); }
  static of(raw: string): UserId { return new UserId(raw); }
  toString(): string { return this.value; }
}

// value_objects/email_address.ts
export class EmailAddress {
  private constructor(private readonly value: string) {}
  static parse(raw: string): EmailAddress {
    if (!/^[^@]+@[^@]+$/.test(raw)) throw new Error("invalid email");
    return new EmailAddress(raw);
  }
  toString(): string { return this.value; }
}

// entities/user.ts — pure, no framework imports
import { UserId } from "../value_objects/user_id";
import { EmailAddress } from "../value_objects/email_address";

export class User {
  constructor(
    public readonly id: UserId,
    private _name: string,
    private _email: EmailAddress,
  ) {}

  // Read accessors — required by infrastructure adapters that need to
  // serialise an aggregate. Encapsulation is preserved because callers
  // can't mutate state through them.
  get name(): string { return this._name; }
  get email(): EmailAddress { return this._email; }

  rename(newName: string): void {
    if (newName.trim().length === 0) throw new Error("name cannot be empty");
    this._name = newName;
  }

  changeEmail(newEmail: EmailAddress): void {
    this._email = newEmail;
  }
}

// ports/user_repository.ts — interface only
import { User } from "../entities/user";
import { UserId } from "../value_objects/user_id";

export interface UserRepository {
  save(user: User): Promise<void>;
  byId(id: UserId): Promise<User | null>;
}
```

## Application (`src/modules/users/application/`)

```ts
// services/register_user_service.ts
import { User } from "../domain/entities/user";
import { EmailAddress } from "../domain/value_objects/email_address";
import { UserRepository } from "../domain/ports/user_repository";
import { UserId } from "../domain/value_objects/user_id";

export interface RegisterUserCommand { name: string; email: string; }
export interface RegisterUserResult { id: string; }

export class RegisterUserService {
  constructor(private readonly users: UserRepository) {}

  async execute(cmd: RegisterUserCommand): Promise<RegisterUserResult> {
    const user = new User(UserId.fresh(), cmd.name, EmailAddress.parse(cmd.email));
    await this.users.save(user);
    return { id: user.id.toString() };
  }
}
```

The application service holds zero business rules — every invariant lives on the entity or value object. The service just orchestrates.

## Infrastructure (`src/modules/users/infrastructure/`)

```ts
// persistence/in_memory_user_repository.ts
import { UserRepository } from "../../domain/ports/user_repository";
import { User } from "../../domain/entities/user";
import { UserId } from "../../domain/value_objects/user_id";

export class InMemoryUserRepository implements UserRepository {
  private store = new Map<string, User>();
  async save(user: User): Promise<void> { this.store.set(user.id.toString(), user); }
  async byId(id: UserId): Promise<User | null> {
    return this.store.get(id.toString()) ?? null;
  }
}
```

Swap for a `PrismaUserRepository` in production. Both implement the same domain port — application code doesn't change.

## Presentation (`src/modules/users/presentation/`)

```ts
// http/user_controller.ts
import { Router, Request, Response } from "express";
import { RegisterUserService } from "../application/services/register_user_service";

export function userRoutes(register: RegisterUserService): Router {
  const r = Router();
  r.post("/users", async (req: Request, res: Response) => {
    try {
      const result = await register.execute({
        name: req.body.name,
        email: req.body.email,
      });
      res.status(201).json(result);
    } catch (e: any) {
      res.status(400).json({ error: e.message });
    }
  });
  return r;
}
```

Presentation translates `req.body` into a command, calls the application service, formats the response. No business logic.

## Composition root (`src/main.ts`)

```ts
import express from "express";
import { InMemoryUserRepository } from "./modules/users/infrastructure/persistence/in_memory_user_repository";
import { RegisterUserService } from "./modules/users/application/services/register_user_service";
import { userRoutes } from "./modules/users/presentation/http/user_controller";

const users = new InMemoryUserRepository();
const register = new RegisterUserService(users);

const app = express();
app.use(express.json());
app.use(userRoutes(register));
app.listen(3000);
```

The composition root is the *only* place that knows about both concrete infrastructure and application — it wires them together. Everything else depends on interfaces.
